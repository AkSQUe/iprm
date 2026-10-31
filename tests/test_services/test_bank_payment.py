"""Тести app.services.bank_payment -- підтвердження оплати з банківської виписки."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.payment_transaction import PaymentTransaction
from app.models.registration import EventRegistration
from app.models.user import User
from app.services.bank_payment import SOURCE_BANK, confirm_bank_payment

MOMENT = datetime(2026, 10, 30, 9, 15, tzinfo=timezone.utc)


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def user(app):
    u = User.create_with_password(
        f'bank-{_uid()}@test.com', 'password123', first_name='Test', last_name='User',
    )
    db.session.flush()
    return u


@pytest.fixture
def instance(app, user):
    c = Course(
        title='Test Course', slug=f'bank-course-{_uid()}',
        event_type='course', base_price=1500, is_active=True,
        created_by=user.id,
    )
    db.session.add(c)
    db.session.flush()
    inst = CourseInstance(
        course_id=c.id, status='active', event_format='offline', price=1500,
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _make_reg(user, instance, **kwargs):
    fields = dict(
        user_id=user.id, instance_id=instance.id,
        phone='+380000000000', specialty='Test', workplace='Test',
        status='pending', payment_status='unpaid', payment_amount=Decimal('1500.00'),
    )
    fields.update(kwargs)
    reg = EventRegistration(**fields)
    db.session.add(reg)
    db.session.flush()
    return reg


@pytest.fixture
def reg_unpaid_1500(app, user, instance):
    return _make_reg(user, instance)


@pytest.fixture
def sent(monkeypatch):
    """Лічильник листів «оплату отримано»."""
    from app.services.email_service import EmailService
    counter = SimpleNamespace(count=0)

    def fake(registration):
        counter.count += 1

    monkeypatch.setattr(EmailService, 'send_payment_confirmation',
                        staticmethod(fake))
    return counter


def _bank_rows(**filters):
    return PaymentTransaction.query.filter_by(source=SOURCE_BANK, **filters).all()


def _utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def test_confirms_unpaid_registration_like_card(app, reg_unpaid_1500, sent):
    r = confirm_bank_payment(f'REG-{reg_unpaid_1500.id}', Decimal('1500.00'),
                             MOMENT, 'bt-77')
    assert (r.status, r.reason) == ('paid', None)
    db.session.refresh(reg_unpaid_1500)
    assert reg_unpaid_1500.payment_status == 'paid'
    assert reg_unpaid_1500.status == 'confirmed'
    assert reg_unpaid_1500.place_number is not None
    assert _utc(reg_unpaid_1500.paid_at) == MOMENT
    assert reg_unpaid_1500.paid_at_precision == 'datetime'
    assert reg_unpaid_1500.payment_id is None
    txn = PaymentTransaction.query.filter_by(
        registration_id=reg_unpaid_1500.id, source='bank').one()
    assert txn.payment_id == 'bt-77' and txn.mapped_status == 'paid'
    assert sent.count == 1


def test_repeat_is_duplicate_without_second_email(app, reg_unpaid_1500, sent):
    ref = f'REG-{reg_unpaid_1500.id}'
    first = confirm_bank_payment(ref, Decimal('1500'), MOMENT, 'bt-dup')
    second = confirm_bank_payment(ref, Decimal('1500'), MOMENT, 'bt-dup')
    assert first.status == 'paid'
    assert (second.status, second.reason) == ('duplicate', None)
    assert sent.count == 1
    assert len(_bank_rows(registration_id=reg_unpaid_1500.id)) == 1


def test_already_paid_is_refused_untouched(app, user, instance, sent):
    manual_moment = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    reg = _make_reg(user, instance, payment_status='paid', status='confirmed')
    reg.set_paid_at(manual_moment, 'date')
    db.session.flush()
    r = confirm_bank_payment(f'REG-{reg.id}', Decimal('1500'), MOMENT, 'bt-1')
    assert (r.status, r.reason) == ('refused', 'already_paid')
    db.session.refresh(reg)
    assert _utc(reg.paid_at) == manual_moment
    assert reg.paid_at_precision == 'date'
    assert _bank_rows(registration_id=reg.id) == []
    assert sent.count == 0


def test_cancelled_registration_refused(app, user, instance, sent):
    reg = _make_reg(user, instance, status='cancelled', payment_status='unpaid')
    r = confirm_bank_payment(f'REG-{reg.id}', Decimal('1500'), MOMENT, 'bt-2')
    assert (r.status, r.reason) == ('refused', 'cancelled')
    db.session.refresh(reg)
    assert reg.payment_status == 'unpaid'
    assert sent.count == 0


def test_refunded_registration_refused(app, user, instance, sent):
    reg = _make_reg(user, instance, payment_status='refunded', status='cancelled')
    r = confirm_bank_payment(f'REG-{reg.id}', Decimal('1500'), MOMENT, 'bt-3')
    assert (r.status, r.reason) == ('refused', 'refunded')
    assert sent.count == 0


def test_amount_tolerance(app, user, instance, sent):
    other = User.create_with_password(
        f'bank-{_uid()}@test.com', 'password123', first_name='Other', last_name='User',
    )
    db.session.flush()
    ok = _make_reg(user, instance)
    bad = _make_reg(other, instance)
    r_ok = confirm_bank_payment(f'REG-{ok.id}', Decimal('1500'), MOMENT, 'bt-ok')
    r_bad = confirm_bank_payment(f'REG-{bad.id}', Decimal('1499.99'), MOMENT, 'bt-bad')
    assert (r_ok.status, r_ok.reason) == ('paid', None)
    assert (r_bad.status, r_bad.reason) == ('refused', 'amount_mismatch')
    assert sent.count == 1


def test_unknown_and_bad_refs(app, sent):
    def outcome(ref, tx):
        r = confirm_bank_payment(ref, Decimal('1'), MOMENT, tx)
        return r.status, r.reason

    assert outcome('REG-999999', 'x1') == ('refused', 'not_found')
    assert outcome('SUR-5', 'x2') == ('refused', 'bad_ref')
    assert outcome('abc', 'x3') == ('refused', 'bad_ref')
    assert outcome('REG-abc', 'x4') == ('refused', 'bad_ref')


def test_confirms_online_enrollment(app, user):
    course = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000), remote_name='Курс',
        slug=f'bank-onl-{_uid()}', price=Decimal('4500'),
        access_url='https://example.test/register/abc', is_published=True,
    )
    db.session.add(course)
    db.session.flush()
    enr = OnlineEnrollment(
        user_id=user.id, online_course_id=course.id,
        payment_amount=Decimal('4500'), payment_status='unpaid', status='pending',
    )
    db.session.add(enr)
    db.session.flush()
    try:
        r = confirm_bank_payment(f'ONL-{enr.id}', Decimal('4500'), MOMENT, 'bt-onl')
        assert (r.status, r.reason) == ('paid', None)
        db.session.refresh(enr)
        assert enr.payment_status == 'paid'
        assert enr.status == 'active'
        assert enr.paid_at_precision == 'datetime'
        txn = PaymentTransaction.query.filter_by(
            enrollment_id=enr.id, source='bank').one()
        assert txn.payment_id == 'bt-onl'
    finally:
        db.session.rollback()
        OnlineEnrollment.query.delete()
        OnlineCourse.query.delete()
        db.session.commit()
