"""Підтверджена, але НЕОПЛАЧЕНА реєстрація: оплата має лишатись доступною.

Стан `confirmed` + `unpaid` -- не екзотика, а штатний крок: менеджер заходу
погоджує участь, гроші ще не надійшли. Саме в ньому реєстрація їде в KeyCRM
як «очікує оплати», щоб було кому дотиснути платіж.

Що тут стережеться: кабінет показує кнопку «Оплатити» для БУДЬ-ЯКОЇ
неоплаченої реєстрації, а сторінка, на яку вона веде, довго вимагала ще й
`status == 'pending'`. Тобто підтвердження мовчки перетворювало кнопку на
глухий кут: ні LiqPay, ні рахунка, ні пояснення. Токен-флоу менеджера
(`complete_payment`) такої вимоги не мав ніколи -- два екрани того самого
платіжного шляху розходились.
"""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from tests import refund_fixtures

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:6]


@pytest.fixture(autouse=True)
def clean(app):
    yield
    refund_fixtures.purge('cup-', 'cup-')


@pytest.fixture(autouse=True)
def _keys(liqpay_keys):
    """Без ключів LiqPay форма не будується -- потрібні кожному тесту."""


@pytest.fixture
def buyer(app):
    item = User.create_with_password(
        f'cup-{_uid()}@test.com', 'password123',
        first_name='Таїсія', last_name='Куцюк', email_confirmed=True,
    )
    db.session.flush()
    return item


def _make_reg(buyer, status):
    course = Course(title='Курс', slug=f'cup-{_uid()}', is_active=False)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='published', price=10000,
        start_date=utcnow() + timedelta(days=30),
    )
    db.session.add(instance)
    db.session.flush()
    item = EventRegistration(
        user_id=buyer.id, instance_id=instance.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status=status, payment_status='unpaid',
        payment_amount=Decimal('10000'),
    )
    db.session.add(item)
    db.session.flush()
    return item


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def test_confirmed_registration_still_offers_liqpay(client, buyer):
    """Кнопка в кабінеті веде на форму оплати, а не в порожню сторінку."""
    reg = _make_reg(buyer, 'confirmed')
    _login(client, buyer)

    page = client.get(f'/registration/{reg.id}').get_data(as_text=True)

    assert 'reg-pay-options' in page
    assert 'liqpay' in page.lower()


def test_confirmed_registration_still_offers_invoice(client, buyer):
    """Рахунок роут віддає й для підтвердженої -- посилання має бути видно."""
    reg = _make_reg(buyer, 'confirmed')
    _login(client, buyer)

    page = client.get(f'/registration/{reg.id}').get_data(as_text=True)

    assert f'/registration/{reg.id}/invoice.pdf' in page


def test_cancelled_registration_offers_no_payment(client, buyer):
    """Скасованій оплата не потрібна -- інакше людина заплатить за ніщо."""
    reg = _make_reg(buyer, 'cancelled')
    _login(client, buyer)

    page = client.get(f'/registration/{reg.id}').get_data(as_text=True)

    assert 'reg-pay-options' not in page


def test_confirmed_registration_banner_says_confirmed(client, buyer):
    """Банер каже правду про статус, а не «заявку подано» вже підтвердженій."""
    reg = _make_reg(buyer, 'confirmed')
    _login(client, buyer)

    page = client.get(f'/registration/{reg.id}').get_data(as_text=True)

    assert 'Реєстрацію підтверджено' in page


def test_completed_registration_banner_says_finished(client, buyer):
    """Захід уже минув -- вітати «заявка подана» означало б збрехати."""
    reg = _make_reg(buyer, 'completed')
    _login(client, buyer)

    page = client.get(f'/registration/{reg.id}').get_data(as_text=True)

    assert 'Захід завершено' in page


def test_only_one_step_is_marked_current(client, buyer):
    """Два підсвічені кроки з трьох -- це вже не індикатор прогресу."""
    reg = _make_reg(buyer, 'confirmed')
    _login(client, buyer)

    page = client.get(f'/registration/{reg.id}').get_data(as_text=True)

    assert page.count('reg-steps__item--current') == 1


def test_pending_registration_keeps_offering_payment(client, buyer):
    """Базовий стан не має постраждати від розширення умови."""
    reg = _make_reg(buyer, 'pending')
    _login(client, buyer)

    page = client.get(f'/registration/{reg.id}').get_data(as_text=True)

    assert 'reg-pay-options' in page
