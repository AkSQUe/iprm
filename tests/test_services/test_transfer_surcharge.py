"""Доплата різниці тарифу при перенесенні."""
from datetime import timedelta
from unittest.mock import MagicMock

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


@pytest.fixture
def mock_liqpay():
    """Той самий фейк, що й у test_payment_ops.py -- MagicMock із
    підписом, що завжди валідний; decode_callback підміняє кожен тест."""
    service = MagicMock()
    service.validate_callback_signature.return_value = True
    return service


def test_callback_credits_surcharge_once(transfer, mock_liqpay):
    """Наскрізно через process_callback (не напряму apply_surcharge) --
    саме тут живуть блокування рядка й звірка суми, додані після рев'ю."""
    from app.services.payment_ops import PaymentOps
    item, reg = transfer
    mock_liqpay.decode_callback.return_value = {
        'order_id': f'SUR-{item.id}', 'status': 'success',
        'payment_id': 'lp-cb-1', 'amount': 500,
    }
    ops = PaymentOps(mock_liqpay)
    ok, msg = ops.process_callback('data', 'sig')
    assert ok
    db.session.refresh(reg)
    assert reg.payment_amount == 1500
    assert item.surcharge_paid_at is not None


def test_repeated_callback_does_not_double_credit(transfer, mock_liqpay):
    """LiqPay повторює callback -- другий виклик того самого order_id не
    повинен додати різницю вдруге. Перевіряємо шлях диспетчеризації
    цілком (parse_order_id -> блокування -> apply_surcharge), а не лише
    сам метод: саме тут регресія в диспетчеризації лишилась би непоміченою."""
    from app.services.payment_ops import PaymentOps
    item, reg = transfer
    mock_liqpay.decode_callback.return_value = {
        'order_id': f'SUR-{item.id}', 'status': 'success',
        'payment_id': 'lp-cb-1', 'amount': 500,
    }
    ops = PaymentOps(mock_liqpay)
    ops.process_callback('data', 'sig')
    ok2, msg2 = ops.process_callback('data', 'sig')
    assert ok2
    db.session.refresh(reg)
    assert reg.payment_amount == 1500


def test_callback_writes_payment_transaction(transfer, mock_liqpay):
    """Доплата -- такі самі гроші, як решта: без рядка в журналі її не
    видно ані звірці за транзакціями, ані бухгалтеру."""
    from app.models.payment_transaction import PaymentTransaction
    from app.services.payment_ops import PaymentOps
    item, reg = transfer
    mock_liqpay.decode_callback.return_value = {
        'order_id': f'SUR-{item.id}', 'status': 'success',
        'payment_id': 'lp-cb-3', 'amount': 500,
    }
    PaymentOps(mock_liqpay).process_callback('data', 'sig')

    txn = PaymentTransaction.query.filter_by(
        order_id=f'SUR-{item.id}').one()
    assert txn.registration_id == reg.id
    assert txn.enrollment_id is None
    assert txn.amount == 500
    assert txn.mapped_status == 'paid'
    assert txn.source == 'callback'
    assert txn.payment_id == 'lp-cb-3'
    assert txn.liqpay_status == 'success'
    assert txn.raw_payload['order_id'] == f'SUR-{item.id}'


def test_repeated_callback_writes_one_transaction(transfer, mock_liqpay):
    """Повтор callback-а не має подвоїти й рядок журналу."""
    from app.models.payment_transaction import PaymentTransaction
    from app.services.payment_ops import PaymentOps
    item, _reg = transfer
    mock_liqpay.decode_callback.return_value = {
        'order_id': f'SUR-{item.id}', 'status': 'success',
        'payment_id': 'lp-cb-4', 'amount': 500,
    }
    ops = PaymentOps(mock_liqpay)
    ops.process_callback('data', 'sig')
    ops.process_callback('data', 'sig')
    assert PaymentTransaction.query.filter_by(
        order_id=f'SUR-{item.id}').count() == 1


def test_callback_rejects_amount_mismatch(transfer, mock_liqpay):
    """payload['amount'] звіряється з transfer.difference -- підозрілу
    суму не зараховуємо мовчки (Знахідка 2 рев'ю)."""
    from app.services.payment_ops import PaymentOps
    item, reg = transfer
    mock_liqpay.decode_callback.return_value = {
        'order_id': f'SUR-{item.id}', 'status': 'success',
        'payment_id': 'lp-cb-2', 'amount': 1,
    }
    ops = PaymentOps(mock_liqpay)
    ok, msg = ops.process_callback('data', 'sig')
    assert not ok
    assert msg == 'amount mismatch'
    db.session.refresh(reg)
    assert reg.payment_amount == 1000
    assert item.surcharge_paid_at is None


# ------------------ звірка зависли доплат ------------------
#
# У перенесення немає колонки payment_status, тож два інші проходи звірки
# (реєстрації й онлайн-курси) його не бачать у принципі. Доплата, що
# застрягла в LiqPay у wait_accept, лишалась би «не надійшла» вічно --
# рівно та аварія, заради якої звірку й заводили.


def test_reconcile_credits_hung_surcharge(transfer, mock_liqpay):
    from app.services.payment_ops import reconcile_pending
    item, reg = transfer
    mock_liqpay.is_configured = True
    mock_liqpay.check_status.side_effect = lambda order_id: (
        {'status': 'success', 'payment_id': 'PAY-SUR', 'amount': 500}
        if order_id == f'SUR-{item.id}' else None
    )

    report = reconcile_pending(service=mock_liqpay)

    db.session.refresh(reg)
    assert reg.payment_amount == 1500
    assert item.surcharge_paid_at is not None
    assert item.surcharge_payment_id == 'PAY-SUR'
    assert any(f'SUR-{item.id}: ok' == line for line in report['details'])


def test_reconcile_leaves_wait_accept_alone(transfer, mock_liqpay):
    """Доки платіж не проведено, звірка мусить мовчати."""
    from app.services.payment_ops import reconcile_pending
    item, reg = transfer
    mock_liqpay.is_configured = True
    mock_liqpay.check_status.side_effect = lambda order_id: (
        {'status': 'wait_accept', 'payment_id': 'PAY-W', 'amount': 500}
        if order_id == f'SUR-{item.id}' else None
    )

    reconcile_pending(service=mock_liqpay)

    db.session.refresh(reg)
    assert reg.payment_amount == 1000
    assert item.surcharge_paid_at is None


def test_reconcile_ignores_closed_surcharge(transfer, mock_liqpay):
    """Закриту доплату не питаємо: звірка не має щочверть години ходити
    до чужого API за тим, що вже зараховано."""
    from app.services.payment_ops import PaymentOps, reconcile_pending
    item, _reg = transfer
    PaymentOps.apply_surcharge(item, payment_id='lp-done', amount=500)
    mock_liqpay.is_configured = True
    mock_liqpay.check_status.return_value = None

    reconcile_pending(service=mock_liqpay)

    asked = [call.args[0] for call in mock_liqpay.check_status.call_args_list]
    assert f'SUR-{item.id}' not in asked


def test_reconcile_refuses_wrong_amount(transfer, mock_liqpay):
    """Сума з LiqPay звіряється з transfer.difference і в звірці теж --
    інакше обхідний шлях приймав би те, що callback відкинув."""
    from app.services.payment_ops import reconcile_pending
    item, reg = transfer
    mock_liqpay.is_configured = True
    mock_liqpay.check_status.side_effect = lambda order_id: (
        {'status': 'success', 'payment_id': 'PAY-BAD', 'amount': 1}
        if order_id == f'SUR-{item.id}' else None
    )

    reconcile_pending(service=mock_liqpay)

    db.session.refresh(reg)
    assert reg.payment_amount == 1000
    assert item.surcharge_paid_at is None


# ------------------ повернення при сплаченій доплаті ------------------
#
# Доплата приходить на власне замовлення SUR-<transfer_id>, але піднімає
# payment_amount реєстрації. Повернення ж завжди йде проти REG-<reg_id>,
# на який ці гроші не приходили: без стелі LiqPay відхилив би повернення
# цілком, і адмін не зміг би повернути навіть первісну суму.


@pytest.fixture
def paid_surcharge(transfer):
    """Доплату 500 зараховано: payment_amount 1500, з них 1000 на REG-."""
    from app.services.payment_ops import PaymentOps
    item, reg = transfer
    PaymentOps.apply_surcharge(item, payment_id='lp-sur-1', amount=500)
    return item, reg


def test_refund_ceiling_excludes_paid_surcharge(paid_surcharge):
    from app.services.payment_ops import resolve_refund_amount
    _item, reg = paid_surcharge
    assert reg.payment_amount == 1500
    assert reg.side_payments_received == 500
    assert reg.refund_available == 1000  # рівно те, що надійшло на REG-
    amount, problem = resolve_refund_amount(reg, None)
    assert problem is None
    assert amount == 1000


def test_refund_over_ceiling_is_refused(paid_surcharge):
    from app.services.payment_ops import resolve_refund_amount
    _item, reg = paid_surcharge
    amount, problem = resolve_refund_amount(reg, '1500')
    assert amount is None
    assert 'залишок' in problem


def test_original_amount_is_refundable(paid_surcharge, monkeypatch):
    """Головне: первісні 1000 повертаються, а не блокуються доплатою."""
    from unittest.mock import MagicMock
    from app.services.payment_ops import PaymentOps
    _item, reg = paid_surcharge
    liqpay = MagicMock()
    liqpay.is_configured = True
    liqpay.create_refund_request.return_value = {'status': 'reversed'}
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_refund_notification',
        staticmethod(lambda *a, **k: None),
    )
    ok, message = PaymentOps(liqpay).initiate_refund(reg, reg.user)
    assert ok, message
    assert reg.refunded_total == 1000
    # LiqPay просили саме про суму, що на це замовлення надходила.
    assert liqpay.create_refund_request.call_args[0][1] == 1000.0


def test_unpaid_surcharge_does_not_shrink_the_ceiling(transfer):
    """Доплата, яка ще не надійшла, грошей нам не додала -- і стелі не
    зменшує."""
    _item, reg = transfer
    assert reg.side_payments_received == 0
    assert reg.refund_available == 1000


def test_surcharge_page_refuses_after_refund_request(client, transfer):
    """Посилання на оплату лишається в пошті 30 днів. Той, хто вже натиснув
    «Прошу повернення коштів», не має змоги підняти payment_amount уже
    після того, як суму повернення порахували."""
    item, _reg = transfer
    transfer_service.request_refund(item, 'Передумав')
    resp = client.get(
        f'/registration/transfer/{item.consent_token}/surcharge',
        follow_redirects=False)
    assert resp.status_code == 302
    assert 'surcharge' not in resp.headers['Location']
