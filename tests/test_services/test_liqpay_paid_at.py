"""Дата оплати LiqPay -- момент платежу з end_date, а не мить callback-у.

Callback буває запізнілим, а звірка зависних платежів (reconcile_pending)
перепитує LiqPay і за години. Якщо брати "зараз", оплата з 23:59 31-го
лягає наступним місяцем. LiqPay віддає момент завершення платежу в
end_date (мілісекунди Unix, UTC) -- його й беремо; без нього -- "зараз".
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import PAID_AT_DATETIME
from app.models.registration import EventRegistration
from app.models.user import User
from app.services.payment_ops import PaymentOps, liqpay_end_date, reconcile_pending
from app.utils import ensure_utc

END_DATE = datetime(2026, 9, 30, 20, 59, 58, 123000, tzinfo=timezone.utc)
END_DATE_MS = int(END_DATE.timestamp() * 1000)


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def instance(app):
    course = Course(title='LiqPay Course', slug=f'lpa-{_uid()}', base_price=1000,
                    is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='active',
                          event_format='offline', price=1000)
    db.session.add(inst)
    db.session.flush()
    return inst


def _reg(instance, payment_status='unpaid'):
    user = User.create_with_password(
        f'lpa-{_uid()}@test.com', 'password123', first_name='A', last_name='B')
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380000000000',
        specialty='T', workplace='T', status='pending',
        payment_status=payment_status, payment_amount=1000,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


@pytest.fixture
def liqpay():
    service = MagicMock()
    service.validate_callback_signature.return_value = True
    service.is_configured = True
    return service


def _success(order_id, **extra):
    payload = {'order_id': order_id, 'status': 'success',
               'payment_id': f'PAY-{_uid()}', 'amount': 1000}
    payload.update(extra)
    return payload


class TestEndDate:
    def test_parses_milliseconds(self):
        assert liqpay_end_date({'end_date': END_DATE_MS}) == END_DATE

    def test_accepts_string(self):
        assert liqpay_end_date({'end_date': str(END_DATE_MS)}) == END_DATE

    @pytest.mark.parametrize('payload', [None, {}, {'end_date': ''},
                                         {'end_date': 'soon'}])
    def test_missing_or_broken_is_none(self, payload):
        assert liqpay_end_date(payload) is None


class TestCallback:
    def test_paid_at_is_end_date(self, app, instance, liqpay):
        reg = _reg(instance)
        liqpay.decode_callback.return_value = _success(
            f'REG-{reg.id}', end_date=END_DATE_MS)

        ok, _ = PaymentOps(liqpay).process_callback('data', 'sig')

        assert ok
        assert ensure_utc(reg.paid_at) == END_DATE
        assert reg.paid_at_precision == PAID_AT_DATETIME

    def test_without_end_date_is_now(self, app, instance, liqpay):
        reg = _reg(instance)
        liqpay.decode_callback.return_value = _success(f'REG-{reg.id}')
        before = datetime.now(timezone.utc)

        PaymentOps(liqpay).process_callback('data', 'sig')

        assert ensure_utc(reg.paid_at) >= before - timedelta(seconds=1)
        assert reg.paid_at_precision == PAID_AT_DATETIME

    def test_online_enrollment_takes_end_date(self, app, liqpay):
        from app.models.online_course import OnlineCourse
        from app.models.online_enrollment import OnlineEnrollment

        user = User.create_with_password(
            f'lpa-{_uid()}@test.com', 'password123', first_name='A', last_name='B')
        course = OnlineCourse(sintegrum_id=int(uuid4().int % 10_000_000),
                              remote_name='Online', slug=f'lpa-{_uid()}', price=500)
        db.session.add(course)
        db.session.flush()
        item = OnlineEnrollment(user_id=user.id, online_course_id=course.id,
                                payment_status='unpaid', payment_amount=500)
        db.session.add(item)
        db.session.flush()
        liqpay.decode_callback.return_value = _success(
            item.order_id, amount=500, end_date=END_DATE_MS)

        PaymentOps(liqpay).process_callback('data', 'sig')

        assert ensure_utc(item.paid_at) == END_DATE
        assert item.paid_at_precision == PAID_AT_DATETIME


def test_reconcile_takes_end_date_not_the_moment_of_check(app, instance, liqpay):
    """Звірка приходить пізніше за платіж -- дата лишається платіжною."""
    reg = _reg(instance, payment_status='pending')
    liqpay.check_status.return_value = _success(
        f'REG-{reg.id}', end_date=END_DATE_MS)

    report = reconcile_pending(service=liqpay)

    assert report['updated'] == 1
    assert ensure_utc(reg.paid_at) == END_DATE
    assert reg.paid_at_precision == PAID_AT_DATETIME
