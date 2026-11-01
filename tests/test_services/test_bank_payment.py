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
    enr_id, course_id = enr.id, course.id
    try:
        r = confirm_bank_payment(f'ONL-{enr.id}', Decimal('4500'), MOMENT, 'bt-onl')
        assert (r.status, r.reason) == ('paid', None)
        db.session.refresh(enr)
        assert enr.payment_status == 'paid'
        assert enr.status == 'active'
        assert enr.paid_at_precision == 'datetime'
        assert enr.payment_method == 'invoice'
        txn = PaymentTransaction.query.filter_by(
            enrollment_id=enr.id, source='bank').one()
        assert txn.payment_id == 'bt-onl'
    finally:
        db.session.rollback()
        OnlineEnrollment.query.filter_by(id=enr_id).delete()
        OnlineCourse.query.filter_by(id=course_id).delete()
        db.session.commit()


def test_concurrent_same_ref_integrity_error_is_tx_used_elsewhere(
        app, user, instance, sent, monkeypatch):
    """Той самий bank_tx_ref, що проскочив повз перевірку, не є помилкою БД:
    унікальний індекс його відсікає, а відповідь -- відмова «операцію вже
    привʼязано до іншого замовлення»; друге замовлення лишається неоплаченим."""
    from app.services import bank_payment

    other = User.create_with_password(
        f'bank-{_uid()}@test.com', 'password123', first_name='O', last_name='U',
    )
    db.session.flush()
    first = _make_reg(user, instance)
    second = _make_reg(other, instance)
    assert confirm_bank_payment(f'REG-{first.id}', Decimal('1500'), MOMENT,
                                'bt-race').status == 'paid'

    real = bank_payment._logged_owner
    seen = []

    def blind_once(ref):
        seen.append(ref)
        return None if len(seen) == 1 else real(ref)

    monkeypatch.setattr(bank_payment, '_logged_owner', blind_once)
    r = confirm_bank_payment(f'REG-{second.id}', Decimal('1500'), MOMENT,
                             'bt-race')
    assert (r.status, r.reason) == ('refused', 'tx_used_elsewhere')
    assert len(_bank_rows(payment_id='bt-race')) == 1
    db.session.refresh(second)
    assert second.payment_status == 'unpaid'


# ---- фінальні правки ревʼю ----

def _second_user():
    other = User.create_with_password(
        f'bank-{_uid()}@test.com', 'password123', first_name='O', last_name='U',
    )
    db.session.flush()
    return other


def test_same_bank_row_for_other_order_is_tx_used_elsewhere(
        app, user, instance, sent):
    """Той самий рядок виписки, привʼязаний до іншої реєстрації, не є
    duplicate: друга реєстрація лишається неоплаченою."""
    first = _make_reg(user, instance)
    second = _make_reg(_second_user(), instance)
    assert confirm_bank_payment(f'REG-{first.id}', Decimal('1500'), MOMENT,
                                'bt-elsewhere').status == 'paid'
    r = confirm_bank_payment(f'REG-{second.id}', Decimal('1500'), MOMENT,
                             'bt-elsewhere')
    assert (r.status, r.reason) == ('refused', 'tx_used_elsewhere')
    db.session.refresh(second)
    assert second.payment_status == 'unpaid'
    assert len(PaymentTransaction.query.filter_by(
        source=SOURCE_BANK, payment_id='bt-elsewhere').all()) == 1


def _add_paid_row(reg, source):
    db.session.add(PaymentTransaction(
        registration_id=reg.id, order_id=f'REG-{reg.id}', mapped_status='paid',
        source=source,
    ))
    db.session.flush()


def test_paid_via_card_then_manual_date_edit_is_liqpay(app, user, instance):
    from app.services.bank_payment import paid_via_map
    reg = _make_reg(user, instance, payment_status='paid')
    _add_paid_row(reg, 'callback')
    _add_paid_row(reg, 'manual')
    assert paid_via_map('registration', [reg.id]) == {reg.id: 'liqpay'}


def test_paid_via_bank_then_manual_date_edit_is_bank(app, user, instance):
    from app.services.bank_payment import paid_via_map
    reg = _make_reg(user, instance, payment_status='paid')
    _add_paid_row(reg, SOURCE_BANK)
    _add_paid_row(reg, 'manual')
    assert paid_via_map('registration', [reg.id]) == {reg.id: 'bank'}


def test_paid_via_manual_then_status_check_is_liqpay(app, user, instance):
    from app.services.bank_payment import paid_via_map
    reg = _make_reg(user, instance, payment_status='paid')
    _add_paid_row(reg, 'manual')
    _add_paid_row(reg, 'status_check')
    assert paid_via_map('registration', [reg.id]) == {reg.id: 'liqpay'}


def test_completed_registration_stays_completed_after_bank_payment(
        app, user, instance, sent):
    reg = _make_reg(user, instance, status='completed')
    r = confirm_bank_payment(f'REG-{reg.id}', Decimal('1500'), MOMENT, 'bt-done')
    assert r.status == 'paid'
    db.session.refresh(reg)
    assert reg.status == 'completed'
    assert reg.payment_status == 'paid'
    assert sent.count == 1


def test_completed_registration_stays_completed_after_card_payment(
        app, user, instance, sent):
    from app.services.payment_ops import PaymentOps
    reg = _make_reg(user, instance, status='completed')
    ok, _ = PaymentOps(None).update_payment_status(
        reg, 'paid', amount=Decimal('1500'), source='callback',
        raw_payload={})
    assert ok
    db.session.refresh(reg)
    assert reg.status == 'completed'
    assert reg.payment_status == 'paid'


def test_missing_expected_amount_is_refused_on_bank_path(
        app, user, instance, sent):
    reg = _make_reg(user, instance, payment_amount=None)
    r = confirm_bank_payment(f'REG-{reg.id}', Decimal('1500'), MOMENT, 'bt-none')
    assert (r.status, r.reason) == ('refused', 'amount_mismatch')
    db.session.refresh(reg)
    assert reg.payment_status == 'unpaid'


def test_bank_confirmation_sets_invoice_method_for_registration(
        app, user, instance, sent):
    reg = _make_reg(user, instance, payment_method='liqpay')
    assert confirm_bank_payment(f'REG-{reg.id}', Decimal('1500'), MOMENT,
                                'bt-method').status == 'paid'
    db.session.refresh(reg)
    assert reg.payment_method == 'invoice'


def test_card_payment_on_cancelled_registration_behaves_as_before(
        app, user, instance, sent):
    """Шлях картки скасованих не чіпаємо: як і раніше, оплата піднімає статус."""
    from app.services.payment_ops import PaymentOps
    reg = _make_reg(user, instance, status='cancelled')
    ok, _ = PaymentOps(None).update_payment_status(
        reg, 'paid', amount=Decimal('1500'), source='callback', raw_payload={})
    assert ok
    db.session.refresh(reg)
    assert reg.payment_status == 'paid'
    assert reg.status == 'confirmed'


# ---- залишкові знахідки ----

def test_post_commit_failure_in_ops_with_own_row_is_paid(
        app, user, instance, sent, monkeypatch):
    """Збій у PaymentOps ПІСЛЯ commit: рядок журналу цього виклику вже є, тож
    відповідь -- paid, а не duplicate (кінцевий стан той самий)."""
    from app.services.payment_ops import PaymentOps
    reg = _make_reg(user, instance)
    real = PaymentOps.update_payment_status

    def commit_then_fail(self, *args, **kwargs):
        real(self, *args, **kwargs)
        return False, 'post-commit failure'

    monkeypatch.setattr(PaymentOps, 'update_payment_status', commit_then_fail)
    r = confirm_bank_payment(f'REG-{reg.id}', Decimal('1500'), MOMENT, 'bt-post')
    assert (r.status, r.reason) == ('paid', None)
    assert len(_bank_rows(payment_id='bt-post')) == 1


def test_logged_owner_failure_in_fallback_raises_unavailable(
        app, user, instance, sent, monkeypatch):
    """Тимчасова помилка БД у запасному шляху -- не 500 і не остаточна
    відмова: сервіс відкочує сесію й сигналізує, що повторити можна."""
    from sqlalchemy.exc import OperationalError
    from app.services import bank_payment
    from app.services.payment_ops import PaymentOps

    reg = _make_reg(user, instance)
    calls = []
    real = bank_payment._logged_owner

    def flaky(ref):
        calls.append(ref)
        if len(calls) == 1:
            return real(ref)
        raise OperationalError('select', {}, Exception('db gone'))

    monkeypatch.setattr(bank_payment, '_logged_owner', flaky)
    monkeypatch.setattr(PaymentOps, 'update_payment_status',
                        lambda self, *a, **k: (False, 'boom'))
    with pytest.raises(bank_payment.BankPaymentUnavailable):
        confirm_bank_payment(f'REG-{reg.id}', Decimal('1500'), MOMENT, 'bt-flaky')
