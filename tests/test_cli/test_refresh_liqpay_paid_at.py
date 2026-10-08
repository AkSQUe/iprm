"""Точний час LiqPay для дозаповнених днем оплат: `flask refresh-liqpay-paid-at`.

Оплата з paid_at_precision='date' несе умовний полудень, хоча LiqPay знає
справжній момент (end_date у відповіді на запит статусу). Команда без
--apply лише друкує план; з --apply ставить end_date з точністю 'datetime',
пише рядок журналу й зрушує updated_at, щоб MM Medic підтягнув зміну.
Клієнт LiqPay замоканий.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import PAID_AT_DATE, PAID_AT_DATETIME
from app.models.payment_transaction import PaymentTransaction
from app.models.registration import EventRegistration
from app.models.user import User
from app.utils import ensure_utc

NOON = datetime(2026, 9, 11, 9, tzinfo=timezone.utc)  # 12:00 за Києвом
OLD_UPDATED_AT = datetime(2026, 9, 20, 8, tzinfo=timezone.utc)
END_DATE = datetime(2026, 9, 10, 17, 42, 5, tzinfo=timezone.utc)
END_DATE_MS = int(END_DATE.timestamp() * 1000)


def _reg(method='liqpay', precision=PAID_AT_DATE):
    user = User.create_with_password(
        f'rlp-{uuid4().hex[:8]}@test.com', 'password123', first_name='A', last_name='B')
    course = Course(title='Refresh', slug=f'rlp-{uuid4().hex[:8]}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='active', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501112233',
        specialty='S', workplace='W', status='confirmed', payment_status='paid',
        payment_method=method, payment_amount=1000,
        paid_at=NOON, paid_at_precision=precision,
    )
    db.session.add(reg)
    db.session.flush()
    reg.updated_at = OLD_UPDATED_AT
    db.session.commit()
    return reg


@pytest.fixture
def liqpay(monkeypatch):
    service = MagicMock()
    service.is_configured = True
    monkeypatch.setattr('app.services.liqpay.get_liqpay_service',
                        lambda *a, **kw: service)
    return service


def _ok(order_id):
    return {'order_id': order_id, 'status': 'success', 'payment_id': 'PAY-77',
            'amount': 1000, 'end_date': END_DATE_MS}


def _run(app, *args):
    return app.test_cli_runner().invoke(args=['refresh-liqpay-paid-at', *args])


def _reload(reg):
    db.session.expire_all()
    return db.session.get(EventRegistration, reg.id)


def _status_check_txns(reg):
    return PaymentTransaction.query.filter_by(
        registration_id=reg.id, source='status_check').all()


def test_without_apply_writes_nothing(app, liqpay):
    reg = _reg()
    liqpay.check_status.side_effect = _ok

    result = _run(app, '--id', str(reg.id))

    assert result.exit_code == 0, result.output
    assert '(date) -> 2026-09-10 20:42:05 (datetime)' in result.output
    fresh = _reload(reg)
    assert ensure_utc(fresh.paid_at) == NOON
    assert fresh.paid_at_precision == PAID_AT_DATE
    assert ensure_utc(fresh.updated_at) == OLD_UPDATED_AT
    assert _status_check_txns(fresh) == []


def test_apply_sets_end_date_logs_and_bumps_updated_at(app, liqpay):
    reg = _reg()
    liqpay.check_status.side_effect = _ok

    result = _run(app, '--id', str(reg.id), '--apply')

    assert result.exit_code == 0, result.output
    fresh = _reload(reg)
    assert ensure_utc(fresh.paid_at) == END_DATE
    assert fresh.paid_at_precision == PAID_AT_DATETIME
    assert ensure_utc(fresh.updated_at) > OLD_UPDATED_AT
    txns = _status_check_txns(fresh)
    assert len(txns) == 1
    assert txns[0].raw_payload['end_date'] == END_DATE_MS
    liqpay.check_status.assert_called_once_with(f'REG-{reg.id}')


def test_one_failing_row_does_not_stop_the_rest(app, liqpay):
    broken, good = _reg(), _reg()

    def _status(order_id):
        if order_id == f'REG-{broken.id}':
            return None
        return _ok(order_id)
    liqpay.check_status.side_effect = _status

    result = _run(app, '--id', str(broken.id), '--id', str(good.id), '--apply')

    assert result.exit_code != 0
    assert f'{broken.id}: LiqPay не відповів' in result.output
    assert _reload(good).paid_at_precision == PAID_AT_DATETIME
    assert _reload(broken).paid_at_precision == PAID_AT_DATE


def test_unsuccessful_payment_is_reported_not_written(app, liqpay):
    """Повернений платіж (reversed) -- не підстава ставити його час."""
    reg = _reg()
    liqpay.check_status.return_value = {'status': 'reversed', 'end_date': END_DATE_MS}

    result = _run(app, '--id', str(reg.id), '--apply')

    assert result.exit_code != 0
    assert "статус 'reversed'" in result.output
    assert _reload(reg).paid_at_precision == PAID_AT_DATE


def test_default_selection_is_liqpay_with_day_only(app, liqpay):
    target = _reg()
    exact = _reg(precision=PAID_AT_DATETIME)
    invoice = _reg(method='invoice')
    liqpay.check_status.side_effect = _ok

    _run(app)

    asked = {call.args[0] for call in liqpay.check_status.call_args_list}
    assert f'REG-{target.id}' in asked
    assert f'REG-{exact.id}' not in asked
    assert f'REG-{invoice.id}' not in asked
