"""Адмінські сповіщення про замовлення онлайн-курсів.

Заходи сповіщали адмінів і про реєстрацію, і про оплату, а онлайн-курси --
ні про що: ONL-7 від 26.09.2026 оплатили переказом на рахунок, і про
замовлення в адмінці дізнались лише з квитанції. Тут перевіряється, що
три моменти, коли адмінові треба знати про замовлення, до нього доходять,
і доходять по одному разу.
"""
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.medical_profile import MedicalProfile
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.rbac import UserRole
from app.models.user import User
from app.services.email_service import EmailService
from app.services.money import format_amount
from app.services.payment_ops import PaymentOps


@pytest.fixture(autouse=True)
def _no_rate_limit():
    from app.extensions import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def clean(app):
    """Сервіси й роути комітять, тож рядки переживають тестову транзакцію.

    Власних користувачів прибираємо теж: тестова БД спільна на сесію, і
    залишені тут витісняли б чужих зі сторінки /api/v1/participants. Роль
    адміна -- разом із ними: SQLite перевикористовує id, і осиротілий рядок
    UserRole зробив би суперадміном випадкового користувача наступного тесту.
    """
    def _wipe():
        OnlineEnrollment.query.delete()
        OnlineCourse.query.delete()
        stale = [row.id for row in
                 User.query.filter(User.email.like('an-%@test.com')).all()]
        if stale:
            for model in (UserRole, AuthIdentity, MedicalProfile):
                model.query.filter(model.user_id.in_(stale)).delete(
                    synchronize_session=False)
            User.query.filter(User.id.in_(stale)).delete(
                synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def sent(monkeypatch):
    """Перехоплені адмінські листи: (event_type, subject, template, context).

    Підмінено саме відправку адресатам, а не резолвер: так тест проходить
    через справжній збір теми й контексту, і шаблон рендериться окремою
    перевіркою нижче.
    """
    calls = []

    def _capture(recipients, *, subject, template_name, context, trigger,
                 registration_id, idempotency_key=None):
        calls.append({
            'trigger': trigger, 'subject': subject,
            'template': template_name, 'context': context,
        })
        return [True]

    monkeypatch.setattr(
        'app.services.notification_recipients.resolve',
        lambda event_type, instance=None, new_status=None: ['admin@test.com'])
    monkeypatch.setattr(EmailService, '_send_to_recipients',
                        staticmethod(_capture))
    monkeypatch.setattr(EmailService, 'send_online_access',
                        staticmethod(lambda *a, **kw: None))
    return calls


@pytest.fixture
def course(app):
    item = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Терапія аутологічною плазмою',
        slug=f'an-{uuid4().hex[:8]}',
        price=Decimal('4500'),
        is_published=True,
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def buyer(app):
    user = User.create_with_password(
        f'an-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Вероніка', last_name='Геращенко', email_confirmed=True,
    )
    db.session.commit()
    return user


@pytest.fixture
def enrollment(app, buyer, course):
    item = OnlineEnrollment(
        user_id=buyer.id, online_course_id=course.id,
        payment_amount=Decimal('4500'), payment_status='unpaid',
        status='pending',
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def ops():
    return PaymentOps(MagicMock(is_configured=True))


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def _of(sent, trigger):
    return [call for call in sent if call['trigger'] == trigger]


# ------------------------------- оплата -------------------------------

def test_payment_notifies_admins_with_amount(ops, enrollment, sent):
    ok, _ = ops.update_enrollment_status(
        enrollment, 'paid', amount=Decimal('4500'), source='manual')

    assert ok
    payments = _of(sent, 'payment')
    assert len(payments) == 1
    assert payments[0]['subject'].startswith(f'Оплата {format_amount(4500)} UAH')
    assert 'Геращенко' in payments[0]['subject']
    assert payments[0]['context']['enrollment'] is enrollment


def test_repeated_paid_signal_does_not_notify_twice(ops, enrollment, sent):
    ops.update_enrollment_status(
        enrollment, 'paid', amount=Decimal('4500'), source='manual')
    ops.update_enrollment_status(
        enrollment, 'paid', amount=Decimal('4500'), source='callback')

    assert len(_of(sent, 'payment')) == 1


def test_rejected_amount_is_not_announced_as_payment(ops, enrollment, sent):
    ok, _ = ops.update_enrollment_status(
        enrollment, 'paid', amount=Decimal('100'), source='callback')

    assert not ok
    assert _of(sent, 'payment') == []


def test_refund_is_not_announced_as_payment(ops, enrollment, sent,
                                            monkeypatch):
    ops.update_enrollment_status(
        enrollment, 'paid', amount=Decimal('4500'), source='manual')
    monkeypatch.setattr('app.services.sintegrum_access.revoke_remote',
                        lambda enrollment: None)
    sent.clear()

    ops.update_enrollment_status(enrollment, 'refunded', source='manual')

    assert _of(sent, 'payment') == []


def test_free_order_is_not_called_a_payment(ops, enrollment, sent):
    enrollment.payment_amount = Decimal('0')
    db.session.commit()

    ops.update_enrollment_status(
        enrollment, 'paid', amount=Decimal('0'), source='manual')

    payments = _of(sent, 'payment')
    assert len(payments) == 1
    assert payments[0]['subject'].startswith('Безкоштовний доступ')


def test_failed_notification_keeps_the_payment(ops, enrollment, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError('smtp down')

    monkeypatch.setattr(EmailService, 'notify_admins_online_order',
                        staticmethod(_boom))
    monkeypatch.setattr(EmailService, 'send_online_access',
                        staticmethod(lambda *a, **kw: None))

    ok, _ = ops.update_enrollment_status(
        enrollment, 'paid', amount=Decimal('4500'), source='manual')

    assert ok
    assert db.session.get(OnlineEnrollment, enrollment.id).is_paid


# --------------------------- нове замовлення ---------------------------

def test_checkout_announces_new_order_once(client, buyer, course, sent):
    _login(client, buyer)

    assert client.get(f'/online-courses/{course.slug}/checkout').status_code == 200
    client.get(f'/online-courses/{course.slug}/checkout')

    orders = _of(sent, 'registration')
    assert len(orders) == 1
    assert orders[0]['subject'].startswith('Нове замовлення онлайн-курсу')


def test_guest_checkout_announces_new_order(client, course, sent,
                                            monkeypatch):
    monkeypatch.setattr('app.online.routes.verify_recaptcha',
                        lambda action=None: True)

    response = client.post(f'/online-courses/{course.slug}/checkout', data={
        'last_name': 'Геращенко', 'first_name': 'Вероніка',
        'email': f'an-guest-{uuid4().hex[:8]}@test.com',
        'phone': '+380671234567', 'consent_data': 'y',
    })

    assert response.status_code == 302
    assert len(_of(sent, 'registration')) == 1


# ------------------------------ рахунок ------------------------------

def _download_invoice(client, enrollment, monkeypatch):
    monkeypatch.setattr('app.services.invoice_service.render_invoice_pdf',
                        lambda order: b'%PDF-1.4 test')
    return client.get(f'/online-courses/orders/{enrollment.id}/invoice.pdf')


def test_first_invoice_download_warns_admins(client, buyer, enrollment, sent,
                                             monkeypatch):
    _login(client, buyer)

    response = _download_invoice(client, enrollment, monkeypatch)

    assert response.status_code == 200
    invoices = _of(sent, 'registration')
    assert len(invoices) == 1
    assert invoices[0]['subject'].startswith('Рахунок на оплату')
    assert db.session.get(OnlineEnrollment, enrollment.id).payment_method == 'invoice'


def test_repeated_invoice_download_stays_quiet(client, buyer, enrollment,
                                               sent, monkeypatch):
    _login(client, buyer)

    _download_invoice(client, enrollment, monkeypatch)
    _download_invoice(client, enrollment, monkeypatch)

    assert len(_of(sent, 'registration')) == 1


# ------------------------------ шаблон ------------------------------

@pytest.mark.parametrize('kind', ['new', 'invoice', 'paid'])
def test_template_renders_order_details(app, enrollment, kind):
    from flask import render_template

    context = EmailService._online_order_admin_context(enrollment, kind)
    html = render_template('emails/admin_online_order.html', **context)

    assert enrollment.order_id in html
    assert enrollment.user.email in html
    assert 'Терапія аутологічною плазмою' in html
    assert format_amount(4500) in html


def test_template_is_shown_in_the_admin_preview(client, app):
    from tests.support.rbac import grant_role

    admin = User.create_with_password(
        f'an-adm-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='А', last_name='Адмін', email_confirmed=True,
    )
    grant_role(admin, 'super_admin')
    db.session.commit()
    _login(client, admin)

    response = client.get('/admin/notifications/templates')

    assert response.status_code == 200
    assert 'admin_online_order.html' in response.get_data(as_text=True)
