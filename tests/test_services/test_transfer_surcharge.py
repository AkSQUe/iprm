"""Доплата різниці тарифу при перенесенні."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import transfer_service
from app.services.payment_ops import parse_order_id
from tests.refund_fixtures import purge

PREFIX = 'rtu-'


@pytest.fixture
def transfer(app, monkeypatch):
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda t: None),
    )
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    db.session.flush()
    user.set_password('x' * 12)
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=1500)
    db.session.add_all([src, dst])
    db.session.flush()
    tariff = InstanceTariff(instance_id=dst.id, name='Практикум', price=1500)
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add_all([tariff, reg])
    db.session.commit()
    item = transfer_service.execute(
        reg, target_instance=dst, initiator='participant', tariff=tariff,
        tariff_decision='surcharge', announced=True,
    )
    yield item, reg
    purge(PREFIX, slug_prefix=PREFIX)


def test_order_id_prefix_is_recognised():
    assert parse_order_id('SUR-42') == ('surcharge', 42)
    assert parse_order_id('REG-42') == ('registration', 42)


def test_surcharge_is_due_before_payment(transfer):
    item, _reg = transfer
    assert item.difference == 500
    assert item.surcharge_due is True


def test_applying_surcharge_tops_up_payment_amount(transfer):
    """Саме тут сума замовлення доганяє новий тариф."""
    from app.services.payment_ops import PaymentOps
    item, reg = transfer
    PaymentOps.apply_surcharge(item, payment_id='lp-1', amount=500)
    db.session.refresh(reg)
    assert reg.payment_amount == 1500
    assert item.surcharge_paid_at is not None
    assert item.surcharge_payment_id == 'lp-1'
    assert item.surcharge_due is False


def test_applying_surcharge_twice_is_ignored(transfer):
    """Повторний callback LiqPay не має додати різницю вдруге."""
    from app.services.payment_ops import PaymentOps
    item, reg = transfer
    PaymentOps.apply_surcharge(item, payment_id='lp-1', amount=500)
    PaymentOps.apply_surcharge(item, payment_id='lp-1', amount=500)
    db.session.refresh(reg)
    assert reg.payment_amount == 1500


def test_unpaid_surcharge_does_not_block_participation(transfer):
    """Рішення власника: участь чинна, доплата висить як борг."""
    item, reg = transfer
    assert reg.status == 'confirmed'
    assert reg.payment_status == 'paid'
