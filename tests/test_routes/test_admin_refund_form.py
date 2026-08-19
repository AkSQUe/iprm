"""Адмін-сторінка повернення коштів.

Перевіряється не верстка, а те, що сторінка справді керує грошима: показує
рекомендацію за Політикою, проводить часткову суму й не дає ввести більше
за залишок. Плюс `next` -- параметр, який приходить з посилання у списку,
тож він мусить лишатись усередині сайту.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from tests import refund_fixtures

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User


@pytest.fixture(autouse=True)
def clean(app):
    """Прибрати за собою закомічене: частина тестів тут комітить."""
    yield
    refund_fixtures.purge('ar-', 'ar-')


@pytest.fixture
def admin(app):
    item = User.create_with_password(
        f'ar-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='А', last_name='Адмін', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return item


@pytest.fixture
def paid_reg(app, admin):
    course = Course(title='Курс', slug=f'ar-{uuid4().hex[:6]}', is_active=False)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='published', price=1000,
        start_date=utcnow() + timedelta(days=5),
    )
    db.session.add(instance)
    db.session.flush()
    item = EventRegistration(
        user_id=admin.id, instance_id=instance.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status='confirmed', payment_status='paid',
        payment_amount=Decimal('1000'), paid_at=utcnow(),
    )
    db.session.add(item)
    db.session.flush()
    return item


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _liqpay(status='reversed'):
    service = MagicMock()
    service.create_refund_request.return_value = {'status': status}
    service.is_configured = True
    return service


def test_page_shows_policy_recommendation(client, admin, paid_reg):
    _login(client, admin)

    response = client.get(f'/admin/refunds/registration/{paid_reg.id}')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    # Захід через 5 днів -- сходинка 50%, тобто 500 грн із 1000.
    assert '50%' in body
    assert '500.00' in body


def test_partial_refund_goes_through(client, admin, paid_reg):
    _login(client, admin)

    with patch('app.admin.routes_refunds.get_liqpay_service',
               return_value=_liqpay()):
        response = client.post(
            f'/admin/refunds/registration/{paid_reg.id}',
            data={'amount': '500', 'reason': 'Заявка за 5 днів'},
        )

    assert response.status_code == 302
    db.session.refresh(paid_reg)
    assert paid_reg.refunded_total == Decimal('500.00')
    assert paid_reg.payment_status == 'paid'


def test_amount_over_remainder_is_refused(client, admin, paid_reg):
    _login(client, admin)
    # Відмова відкочує сесію; без коміту разом з нею зникла б і сама
    # реєстрація, і перевіряти після запиту було б нічого.
    db.session.commit()
    liqpay = _liqpay()

    with patch('app.admin.routes_refunds.get_liqpay_service',
               return_value=liqpay):
        response = client.post(
            f'/admin/refunds/registration/{paid_reg.id}',
            data={'amount': '1500'},
        )

    assert response.status_code == 302
    liqpay.create_refund_request.assert_not_called()
    db.session.refresh(paid_reg)
    assert paid_reg.refunded_total == Decimal('0')


def test_external_next_is_ignored(client, admin, paid_reg):
    """`next` на чужий домен не має ставати редиректом з адмінки."""
    _login(client, admin)

    with patch('app.admin.routes_refunds.get_liqpay_service',
               return_value=_liqpay()):
        response = client.post(
            f'/admin/refunds/registration/{paid_reg.id}?next=https://evil.test',
            data={'amount': '100'},
        )

    assert response.status_code == 302
    assert 'evil.test' not in response.headers['Location']


def test_unpaid_registration_cannot_be_opened_for_refund(client, admin, paid_reg):
    paid_reg.payment_status = 'unpaid'
    db.session.flush()
    _login(client, admin)
    liqpay = _liqpay()

    with patch('app.admin.routes_refunds.get_liqpay_service',
               return_value=liqpay):
        response = client.post(
            f'/admin/refunds/registration/{paid_reg.id}', data={'amount': '100'})

    assert response.status_code == 302
    liqpay.create_refund_request.assert_not_called()


def test_requires_admin(client, app, paid_reg):
    plain = User.create_with_password(
        f'ar-plain-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Не', last_name='Адмін', email_confirmed=True,
    )
    db.session.flush()
    _login(client, plain)

    response = client.get(f'/admin/refunds/registration/{paid_reg.id}')

    assert response.status_code in (302, 403, 404)
