"""Кнопка «Звірити з LiqPay» на сторінці інтеграції.

Навіщо кнопка взагалі: замовлення в `pending` -- це гроші в дорозі, і вийти
з цього стану воно може лише повторним колбеком (бік LiqPay, загублений
ніхто не перезапитує) або заходом самого платника на сторінку оплати. Якщо
не сталося ні того, ні іншого, рядок висить вічно -- разом із листом про
оплату, подією партнеру й вивозом у KeyCRM.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User

URL = '/admin/liqpay/reconcile'


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'lpr-adm-{_uid()}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


@pytest.fixture
def pending_reg(app, admin):
    course = Course(
        title='Курс', slug=f'lpr-{_uid()}', event_type='course',
        base_price=1000, is_active=False, created_by=admin.id,
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='active', event_format='offline', price=1000,
    )
    db.session.add(inst)
    db.session.flush()

    buyer = User.create_with_password(
        f'lpr-{_uid()}@test.com', 'password123',
        first_name='B', last_name='U',
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=buyer.id, instance_id=inst.id,
        phone='+380000000000', specialty='Х', workplace='Л',
        status='pending', payment_status='pending', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _liqpay(monkeypatch, status):
    """Підмінити LiqPay так, як його бачить `reconcile_pending`.

    Патчимо в модулі-джерелі, а не в місці виклику: сервіс дістається
    відкладеним імпортом усередині функції.
    """
    service = MagicMock()
    service.is_configured = True
    service.check_status.return_value = {
        'status': status, 'payment_id': f'PAY-{_uid()}', 'amount': 1000,
    }
    monkeypatch.setattr('app.services.liqpay.get_liqpay_service',
                        lambda: service)
    return service


def test_requires_admin(client):
    resp = client.post(URL)
    assert resp.status_code in (302, 401, 403)


def test_button_is_reachable_from_the_integration_page(
        client, admin, pending_reg, liqpay_keys):
    """Дія, якої не видно в адмінці, не існує: наступного разу її шукатимуть
    у коді, а знайдуть спосіб зробити те саме руками в БД."""
    _login(client, admin)

    body = client.get('/admin/liqpay').get_data(as_text=True)

    assert URL in body


def test_success_from_liqpay_marks_registration_paid(
        client, admin, pending_reg, monkeypatch):
    """Головне, заради чого кнопка існує: після відновлення верифікації
    один натиск догорає статус, а з ним і все, що на ньому висить."""
    _liqpay(monkeypatch, 'success')
    _login(client, admin)

    resp = client.post(URL)

    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/liqpay')
    assert pending_reg.payment_status == 'paid'
    assert pending_reg.status == 'confirmed'


def test_still_wait_accept_leaves_everything_alone(
        client, admin, pending_reg, monkeypatch):
    """Доки магазин не пройшов верифікацію, LiqPay і далі каже
    `wait_accept` -- кнопка мусить чесно нічого не змінити."""
    service = _liqpay(monkeypatch, 'wait_accept')
    _login(client, admin)

    resp = client.post(URL)

    # Не лише «не змінилось»: без цієї перевірки тест зеленів би й на 404,
    # тобто не міг би впасти з правильної причини.
    assert resp.status_code == 302
    service.check_status.assert_called_once_with(f'REG-{pending_reg.id}')
    assert pending_reg.payment_status == 'pending'


def test_report_is_shown_to_admin(client, admin, pending_reg, monkeypatch):
    _liqpay(monkeypatch, 'wait_accept')
    _login(client, admin)

    resp = client.post(URL, follow_redirects=True)

    assert resp.status_code == 200
    assert f'REG-{pending_reg.id}' in resp.get_data(as_text=True)


def test_unconfigured_liqpay_says_so_instead_of_500(
        client, admin, pending_reg, monkeypatch):
    """Кнопка на сторінці, де ключі ще не збережені, мусить сказати про це
    словами -- як «Тестувати з'єднання» поруч."""
    service = MagicMock()
    service.is_configured = False
    monkeypatch.setattr('app.services.liqpay.get_liqpay_service',
                        lambda: service)
    _login(client, admin)

    resp = client.post(URL, follow_redirects=True)

    assert resp.status_code == 200
    assert 'LiqPay не налаштовано' in resp.get_data(as_text=True)
    service.check_status.assert_not_called()
