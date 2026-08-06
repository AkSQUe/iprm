"""Лист про оплату: промокод-подяка і зворотні шляхи на сайт.

Раніше цей лист був глухим кутом -- квитанція без жодного посилання.
Перевіряємо, що в ньому є кабінет, календар, реферальне посилання і
персональний код, і що видача коду ідемпотентна (повторний лист не
плодить знижок).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.email_log import EmailLog
from app.models.email_settings import EmailSettings
from app.models.mixins import utcnow
from app.models.notification_rule import NotificationRule
from app.models.promo_code import PromoCode
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import promo_service
from app.services.email_service import EmailService
from app.utils import ensure_utc


@pytest.fixture(autouse=True)
def _email_enabled(app):
    settings = EmailSettings.get()
    settings.is_enabled = True
    settings.smtp_server = 'localhost'
    settings.smtp_port = 25
    settings.smtp_username = 'noreply@test.local'
    settings.default_sender = 'noreply@test.local'
    # Невдалі листи інших тестів залишаються в EmailLog і відкривають
    # circuit breaker -- тоді наш лист не рендериться взагалі, і тест падає
    # не на тому, що перевіряє.
    EmailLog.query.filter_by(status='failed').delete()
    db.session.commit()
    yield
    settings.is_enabled = False
    db.session.commit()


@pytest.fixture
def site(app):
    settings = SiteSettings.get()
    settings.website_url = 'https://plasma-regen.com'
    settings.thankyou_promo_enabled = True
    settings.thankyou_promo_percent = 15
    settings.thankyou_promo_days = 30
    settings.referral_enabled = True
    db.session.commit()
    return settings


@pytest.fixture
def registration(app):
    course = Course(title='PRP-практикум', slug=f'pay-{uuid4().hex[:6]}',
                    is_active=True)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        location='Київ, вул. Хрещатик, 1',
        start_date=utcnow() + timedelta(days=14),
    )
    db.session.add(instance)
    user = User.create_with_password(
        f'pay-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Олена', last_name='Шевченко', email_confirmed=True,
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501112233',
        specialty='Дерматолог', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=Decimal('12500'),
        place_number=7,
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def _send(monkeypatch, registration):
    """Сформувати лист, не відкриваючи SMTP. Повертає EmailLog."""
    monkeypatch.setattr('app.services.email_service.Thread',
                        lambda *a, **kw: type('T', (), {
                            'start': lambda self: None, 'daemon': True,
                        })())
    return EmailService.send_payment_confirmation(registration)


# ---------- промокод-подяка ----------

def test_no_code_when_disabled(site, registration):
    site.thankyou_promo_enabled = False
    db.session.commit()
    assert promo_service.issue_thankyou_code(registration) is None


def test_no_code_when_percent_is_meaningless(site, registration):
    site.thankyou_promo_percent = 0
    db.session.commit()
    assert promo_service.issue_thankyou_code(registration) is None


def test_code_is_single_use_and_expires(site, registration):
    promo = promo_service.issue_thankyou_code(registration)
    db.session.commit()

    assert promo.discount_type == 'percent'
    assert promo.discount_value == Decimal('15')
    assert promo.max_uses == 1 and promo.per_user_limit == 1
    assert promo.code.startswith(promo_service.THANKYOU_PREFIX)
    assert promo.issued_for_registration_id == registration.id
    # Область дії порожня: сенс коду -- відправити людину обирати НАСТУПНИЙ курс.
    assert promo.course_id is None and promo.instance_id is None
    # ensure_utc: SQLite віддає datetime без tz.
    delta = ensure_utc(promo.valid_until) - utcnow()
    assert timedelta(days=29) < delta <= timedelta(days=30)


def test_issue_is_idempotent(site, registration):
    """Ретрай листа не має роздавати другу знижку."""
    first = promo_service.issue_thankyou_code(registration)
    db.session.commit()
    second = promo_service.issue_thankyou_code(registration)
    db.session.commit()

    assert first.id == second.id
    assert PromoCode.query.filter_by(
        issued_for_registration_id=registration.id).count() == 1


def test_issued_code_validates_for_another_course(site, registration):
    promo = promo_service.issue_thankyou_code(registration)
    db.session.commit()

    other = CourseInstance(
        course_id=registration.instance.course_id, status='published',
        price=Decimal('10000'), start_date=utcnow() + timedelta(days=60),
    )
    db.session.add(other)
    db.session.flush()

    found, discount, final = promo_service.validate(
        promo.code, instance=other, amount=Decimal('10000'),
    )
    assert found.id == promo.id
    assert discount == Decimal('1500.00')
    assert final == Decimal('8500.00')


# ---------- сам лист ----------

def test_email_has_ways_back_to_the_site(site, registration, monkeypatch):
    log = _send(monkeypatch, registration)
    body = log.html_body or ''

    assert '/auth/account' in body, 'немає кнопки в кабінет'
    assert 'utm_source=email' in body, 'посилання без utm -- клік не виміряти'
    assert 'calendar.google.com' in body, 'немає "додати в календар"'
    assert 'ref=' in body, 'немає реферального посилання'

    promo = PromoCode.query.filter_by(
        issued_for_registration_id=registration.id).one()
    assert promo.code in body, 'промокод не потрапив у лист'


def test_email_carries_ics_attachment(site, registration, monkeypatch):
    captured = {}
    original = EmailService.send_email

    def spy(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(EmailService, 'send_email', staticmethod(spy))
    _send(monkeypatch, registration)

    attachments = captured.get('attachments') or []
    assert len(attachments) == 1
    filename, mimetype, data = attachments[0]
    assert filename.endswith('.ics')
    assert b'BEGIN:VEVENT' in data


def test_zero_amount_is_not_shown_as_broken_payment(site, registration,
                                                    monkeypatch):
    """"Сума: 0 UAH" виглядала як зламаний платіж, а це оплата промокодом."""
    registration.payment_amount = Decimal('0')
    registration.discount_amount = Decimal('12500')
    db.session.commit()

    log = _send(monkeypatch, registration)
    body = log.html_body or ''
    assert 'Оплачено промокодом' in body
    assert '0 UAH' not in body


def test_referral_block_hidden_when_program_is_off(site, registration,
                                                   monkeypatch):
    site.referral_enabled = False
    db.session.commit()

    log = _send(monkeypatch, registration)
    assert 'Запросіть колегу' not in (log.html_body or '')


def test_guest_without_password_gets_token_link_not_login(site, registration,
                                                          monkeypatch):
    """Гість має акаунт без пароля: /auth/account зустрів би його логіном."""
    AuthIdentity.query.filter_by(user_id=registration.user_id).delete()
    db.session.commit()
    registration.issue_completion_token()
    db.session.commit()
    assert registration.user.has_password is False

    log = _send(monkeypatch, registration)
    body = log.html_body or ''

    assert f'/registration/complete/{registration.completion_token}/pay' in body
    assert '/auth/account' not in body
    assert 'Створити кабінет' in body


# ---------- admin-нотифікація ----------

def _admin_log(registration):
    return (EmailLog.query
            .filter_by(template_name='admin_event_notification',
                       registration_id=registration.id)
            .order_by(EmailLog.id.desc())
            .first())


@pytest.fixture
def admin(app):
    """Активний адмін -- інакше resolve() поверне порожній список."""
    u = User.create_with_password(
        f'adm-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Адмін', last_name='Тестовий', email_confirmed=True,
    )
    u.is_admin = True
    u.is_active = True
    db.session.flush()
    NotificationRule.query.delete()
    db.session.add(NotificationRule(event_type='payment'))
    db.session.commit()
    return u


def test_admin_email_carries_money_and_contacts(site, registration, admin,
                                                monkeypatch):
    """Раніше адмін бачив лише ім'я і № реєстрації -- суму треба було
    шукати в адмінці."""
    _send(monkeypatch, registration)
    log = _admin_log(registration)
    assert log is not None, 'admin-нотифікація не сформувалась'
    body = log.html_body or ''

    assert '12500 UAH' in body
    assert '+380501112233' in body
    assert 'tel:+380501112233' in body
    assert f'mailto:{registration.user.email}' in body
    assert 'Дерматолог' in body and 'Клініка' in body


def test_admin_subject_leads_with_the_amount(site, registration, admin,
                                             monkeypatch):
    """У списку листів адмін відрізняє платежі саме за сумою."""
    _send(monkeypatch, registration)
    assert _admin_log(registration).subject.startswith('Оплата 12500 UAH:')


def test_admin_email_explains_zero_amount(site, registration, admin,
                                          monkeypatch):
    registration.payment_amount = Decimal('0')
    registration.discount_amount = Decimal('12500')
    db.session.commit()

    _send(monkeypatch, registration)
    body = _admin_log(registration).html_body or ''
    assert 'Оплачено промокодом' in body
    assert '-12500 UAH' in body and 'було 12500 UAH' in body


def test_no_promo_is_issued_when_sending_is_disabled(site, registration,
                                                     monkeypatch):
    """Вимкнена розсилка не має плодити коди, яких ніхто не отримає."""
    email_settings = EmailSettings.get()
    email_settings.is_enabled = False
    db.session.commit()

    _send(monkeypatch, registration)

    assert PromoCode.query.filter_by(
        issued_for_registration_id=registration.id).count() == 0
