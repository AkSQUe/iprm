"""Відкладений лист "Реєстрацію підтверджено" та формат сум.

Хто платить одразу (підтверджує платіж у застосунку банку), встигав
отримати лист "до оплати" ще під час платежу. Пауза дає платежу дійти, і
якщо оплата надійшла -- лист не йде взагалі.

Окремо перевіряємо формат сум: `| int` округлював залишок 0.60 грн після
промокоду до нуля, і лист казав "0 UAH" (REG-4299/4300).
"""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.email_log import EmailLog
from app.models.email_settings import EmailSettings
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services.email_service import EmailService
from app.services.money import format_amount, money
from app.utils import ensure_utc


# ---------- формат сум ----------

# Розряди -- нерозривним пробілом: «20000 UAH» читається як набір цифр,
# який доводиться рахувати очима (services/money.format_amount).
@pytest.mark.parametrize('value,expected', [
    (Decimal('6000.00'), '6 000'),
    (Decimal('0.60'), '0.60'),      # саме цей випадок друкувався як "0"
    (Decimal('0.05'), '0.05'),
    (Decimal('12500'), '12 500'),
    (Decimal('1234.50'), '1 234.50'),
    (0, '0'),
    (None, ''),
])
def test_amount_keeps_kopiykas_only_when_they_exist(value, expected):
    assert format_amount(value) == expected


def test_money_appends_currency():
    assert money(Decimal('0.60')) == '0.60 UAH'
    assert money(None) == ''


# ---------- відкладене надсилання ----------

@pytest.fixture(autouse=True)
def _email_enabled(app):
    settings = EmailSettings.get()
    settings.is_enabled = True
    settings.smtp_server = 'localhost'
    settings.smtp_port = 25
    settings.smtp_username = 'noreply@test.local'
    settings.default_sender = 'noreply@test.local'
    EmailLog.query.filter_by(status='failed').delete()
    db.session.commit()
    yield
    settings.is_enabled = False
    db.session.commit()


@pytest.fixture
def site(app):
    settings = SiteSettings.get()
    settings.website_url = 'https://plasma-regen.com'
    settings.registration_email_delay_minutes = 5
    db.session.commit()
    return settings


@pytest.fixture
def registration(app):
    course = Course(title='PRP-практикум', slug=f'dl-{uuid4().hex[:6]}',
                    is_active=True)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=utcnow() + timedelta(days=20),
    )
    db.session.add(instance)
    user = User.create_with_password(
        f'dl-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Дмитро', last_name='Тестовий', email_confirmed=True,
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501112233',
        specialty='Дерматолог', workplace='Клініка', status='pending',
        payment_status='unpaid', payment_amount=Decimal('6000'),
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def _no_smtp(monkeypatch):
    monkeypatch.setattr('app.services.email_service.Thread',
                        lambda *a, **kw: type('T', (), {
                            'start': lambda self: None, 'daemon': True,
                        })())


def _confirmation_logs(registration):
    return EmailLog.query.filter_by(
        template_name='registration_confirmed',
        registration_id=registration.id).count()


def test_unpaid_registration_is_deferred(site, registration):
    assert EmailService.schedule_registration_confirmation(registration) is True
    db.session.commit()

    due = ensure_utc(registration.confirmation_email_due_at) - utcnow()
    assert timedelta(minutes=4) < due <= timedelta(minutes=5)


def test_paid_registration_is_not_deferred(site, registration):
    """Безкоштовній участі чекати нічого -- лист має піти одразу."""
    registration.payment_status = 'paid'
    db.session.commit()

    assert EmailService.schedule_registration_confirmation(registration) is False
    assert registration.confirmation_email_due_at is None


def test_invoice_payment_is_not_deferred(site, registration):
    """Оплата за рахунком іде через банк -- гонки з онлайн-платежем немає,
    а лист це інструкція, як завантажити рахунок."""
    registration.payment_method = 'invoice'
    db.session.commit()

    assert EmailService.schedule_registration_confirmation(registration) is False
    assert registration.confirmation_email_due_at is None


def test_zero_delay_keeps_old_behaviour(site, registration):
    site.registration_email_delay_minutes = 0
    db.session.commit()

    assert EmailService.schedule_registration_confirmation(registration) is False
    assert registration.confirmation_email_due_at is None


def test_due_letter_is_sent_when_still_unpaid(site, registration, monkeypatch):
    _no_smtp(monkeypatch)
    registration.confirmation_email_due_at = utcnow() - timedelta(seconds=1)
    db.session.commit()

    sent, skipped = EmailService.send_due_registration_confirmations()

    assert (sent, skipped) == (1, 0)
    assert _confirmation_logs(registration) == 1
    assert registration.confirmation_email_due_at is None


def test_payment_within_the_window_cancels_the_letter(site, registration,
                                                      monkeypatch):
    """Головний сценарій: оплатив одразу -- листа "до оплати" не отримав."""
    _no_smtp(monkeypatch)
    registration.confirmation_email_due_at = utcnow() - timedelta(seconds=1)
    registration.payment_status = 'paid'
    db.session.commit()

    sent, skipped = EmailService.send_due_registration_confirmations()

    assert (sent, skipped) == (0, 1)
    assert _confirmation_logs(registration) == 0
    assert registration.confirmation_email_due_at is None


def test_cancelled_registration_gets_no_letter(site, registration, monkeypatch):
    _no_smtp(monkeypatch)
    registration.confirmation_email_due_at = utcnow() - timedelta(seconds=1)
    registration.status = 'cancelled'
    db.session.commit()

    sent, skipped = EmailService.send_due_registration_confirmations()
    assert (sent, skipped) == (0, 1)
    assert _confirmation_logs(registration) == 0


def test_not_due_yet_is_left_alone(site, registration, monkeypatch):
    _no_smtp(monkeypatch)
    registration.confirmation_email_due_at = utcnow() + timedelta(minutes=3)
    db.session.commit()

    assert EmailService.send_due_registration_confirmations() == (0, 0)
    assert registration.confirmation_email_due_at is not None


def test_payment_ops_cancels_pending_letter(site, registration):
    registration.confirmation_email_due_at = utcnow() + timedelta(minutes=4)
    db.session.commit()

    assert EmailService.cancel_pending_registration_confirmation(registration) is True
    assert registration.confirmation_email_due_at is None
    # Повторний виклик нічого не робить -- ознака вже знята.
    assert EmailService.cancel_pending_registration_confirmation(registration) is False


def test_failed_deferral_falls_back_to_sending_now(site, registration,
                                                    monkeypatch):
    """Реєстрація без жодного листа гірша за лист, що прийшов зарано."""
    _no_smtp(monkeypatch)
    from app.registration.routes import _deliver_registration_confirmation

    def boom(_reg):
        raise RuntimeError('БД недоступна')

    monkeypatch.setattr(EmailService, 'schedule_registration_confirmation',
                        staticmethod(boom))

    _deliver_registration_confirmation(registration)

    assert _confirmation_logs(registration) == 1


def test_letter_shows_kopiykas_left_after_promo(site, registration, monkeypatch):
    """Регресія REG-4299: до сплати 0.60, а в листі стояло "0 UAH"."""
    _no_smtp(monkeypatch)
    registration.payment_amount = Decimal('0.60')
    registration.discount_amount = Decimal('5999.40')
    registration.confirmation_email_due_at = utcnow() - timedelta(seconds=1)
    db.session.commit()

    EmailService.send_due_registration_confirmations()

    log = EmailLog.query.filter_by(
        template_name='registration_confirmed',
        registration_id=registration.id).first()
    body = log.html_body or ''
    assert '0.60 UAH' in body
    # Саме так виглядав баг: ціла частина замість суми.
    assert '>0 UAH<' not in body and '0 UAH (' not in body
