"""Tests for app.services.payment_ops -- payment state machine."""
import pytest
from unittest.mock import MagicMock, patch
from app.extensions import db
from app.models.user import User
from app.models.event import Event
from app.models.registration import EventRegistration
from app.services.payment_ops import PaymentOps, STATUS_MAP, ALLOWED_TRANSITIONS


@pytest.fixture
def user(app):
    from uuid import uuid4
    u = User(email=f'pay-{uuid4().hex[:6]}@test.com', first_name='Test', last_name='User')
    u.set_password('password123')
    db.session.add(u)
    db.session.flush()
    return u


@pytest.fixture
def event(app, user):
    e = Event(
        from uuid import uuid4 as _u
        title='Test Event', slug=f'test-event-{_u().hex[:6]}',
        event_type='course', event_format='offline', status='active',
        price=1000, is_active=True, created_by=user.id,
    )
    db.session.add(e)
    db.session.flush()
    return e


@pytest.fixture
def registration(app, user, event):
    reg = EventRegistration(
        user_id=user.id, event_id=event.id,
        phone='+380000000000', specialty='Test', workplace='Test',
        status='pending', payment_status='unpaid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


@pytest.fixture
def mock_liqpay():
    service = MagicMock()
    service.validate_callback_signature.return_value = True
    service.is_configured = True
    return service


@pytest.fixture
def ops(mock_liqpay):
    return PaymentOps(mock_liqpay)


class TestStatusMap:
    def test_success_maps_to_paid(self):
        assert STATUS_MAP['success'] == 'paid'

    def test_sandbox_maps_to_paid(self):
        assert STATUS_MAP['sandbox'] == 'paid'

    def test_failure_maps_to_unpaid(self):
        assert STATUS_MAP['failure'] == 'unpaid'

    def test_reversed_maps_to_refunded(self):
        assert STATUS_MAP['reversed'] == 'refunded'


class TestAllowedTransitions:
    def test_unpaid_can_go_to_paid(self):
        assert 'paid' in ALLOWED_TRANSITIONS['unpaid']

    def test_paid_can_go_to_refunded(self):
        assert 'refunded' in ALLOWED_TRANSITIONS['paid']

    def test_refunded_cannot_go_anywhere(self):
        assert len(ALLOWED_TRANSITIONS['refunded']) == 0

    def test_paid_cannot_go_to_unpaid(self):
        assert 'unpaid' not in ALLOWED_TRANSITIONS['paid']


class TestUpdatePaymentStatus:
    def test_unpaid_to_paid(self, ops, registration):
        ok, msg = ops.update_payment_status(registration, 'paid', 'PAY-123', amount=1000)
        assert ok
        assert msg == 'ok'
        assert registration.payment_status == 'paid'
        assert registration.status == 'confirmed'
        assert registration.payment_id == 'PAY-123'
        assert registration.paid_at is not None

    def test_paid_to_refunded(self, ops, registration):
        registration.payment_status = 'paid'
        registration.status = 'confirmed'
        db.session.flush()

        ok, msg = ops.update_payment_status(registration, 'refunded')
        assert ok
        assert registration.payment_status == 'refunded'
        assert registration.status == 'cancelled'

    def test_invalid_transition_is_noop(self, ops, registration):
        registration.payment_status = 'refunded'
        db.session.flush()

        ok, msg = ops.update_payment_status(registration, 'paid')
        assert ok
        assert msg == 'no-op transition'
        assert registration.payment_status == 'refunded'

    def test_amount_mismatch_rejected(self, ops, registration):
        ok, msg = ops.update_payment_status(registration, 'paid', 'PAY-X', amount=500)
        assert not ok
        assert msg == 'amount mismatch'
        assert registration.payment_status == 'unpaid'


class TestProcessCallback:
    def test_invalid_signature_rejected(self, ops, mock_liqpay):
        mock_liqpay.validate_callback_signature.return_value = False
        ok, msg = ops.process_callback('data', 'sig')
        assert not ok
        assert msg == 'invalid signature'

    def test_unknown_order_id_rejected(self, ops, mock_liqpay):
        mock_liqpay.decode_callback.return_value = {'order_id': 'UNKNOWN-1', 'status': 'success'}
        ok, msg = ops.process_callback('data', 'sig')
        assert not ok
        assert msg == 'unknown order_id'

    def test_successful_payment(self, ops, mock_liqpay, registration):
        mock_liqpay.decode_callback.return_value = {
            'order_id': f'REG-{registration.id}',
            'status': 'success',
            'payment_id': 'PAY-999',
            'amount': 1000,
        }
        ok, msg = ops.process_callback('data', 'sig')
        assert ok
        assert registration.payment_status == 'paid'

    def test_idempotent_duplicate(self, ops, mock_liqpay, registration):
        registration.payment_status = 'paid'
        registration.payment_id = 'PAY-DUP'
        db.session.flush()

        mock_liqpay.decode_callback.return_value = {
            'order_id': f'REG-{registration.id}',
            'status': 'success',
            'payment_id': 'PAY-DUP',
        }
        ok, msg = ops.process_callback('data', 'sig')
        assert ok
        assert msg == 'already processed'
