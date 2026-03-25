"""Tests for app.payments routes -- callback, success, failure."""
import base64
import hashlib
import json
import pytest
from uuid import uuid4
from unittest.mock import patch

from app.extensions import db
from app.models.user import User
from app.models.event import Event
from app.models.registration import EventRegistration


def _uid():
    return uuid4().hex[:8]


def _make_liqpay_data(payload, private_key='test_private_key'):
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    data_b64 = base64.b64encode(raw).decode('ascii')
    sign_str = (private_key + data_b64 + private_key).encode('utf-8')
    sha1 = hashlib.sha1(sign_str).digest()
    signature = base64.b64encode(sha1).decode('ascii')
    return data_b64, signature


@pytest.fixture
def user(app):
    u = User(email=f'pay-route-{_uid()}@test.com', first_name='Test', last_name='User')
    u.set_password('password123')
    db.session.add(u)
    db.session.flush()
    return u


@pytest.fixture
def event(app, user):
    e = Event(
        title='Test Event', slug=f'test-event-{_uid()}',
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


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


class TestLiqPayCallback:
    def test_missing_data_returns_400(self, client):
        resp = client.post('/payments/liqpay/callback', data={})
        assert resp.status_code == 400

    def test_missing_signature_returns_400(self, client):
        resp = client.post('/payments/liqpay/callback', data={'data': 'abc'})
        assert resp.status_code == 400

    @patch('app.payments.routes.get_liqpay_service')
    def test_invalid_signature_returns_400(self, mock_get_svc, client):
        mock_svc = mock_get_svc.return_value
        mock_svc.validate_callback_signature.return_value = False
        resp = client.post('/payments/liqpay/callback', data={
            'data': 'abc', 'signature': 'bad',
        })
        assert resp.status_code == 400

    @patch('app.payments.routes.get_liqpay_service')
    def test_valid_callback_returns_200(self, mock_get_svc, client, registration):
        mock_svc = mock_get_svc.return_value
        mock_svc.validate_callback_signature.return_value = True
        payload = {
            'order_id': f'REG-{registration.id}',
            'status': 'success',
            'payment_id': f'PAY-{_uid()}',
            'amount': 1000,
        }
        raw = json.dumps(payload).encode('utf-8')
        data_b64 = base64.b64encode(raw).decode('ascii')
        mock_svc.decode_callback.return_value = payload

        resp = client.post('/payments/liqpay/callback', data={
            'data': data_b64, 'signature': 'valid',
        })
        assert resp.status_code == 200


class TestSuccessPage:
    def test_unauthenticated_redirects(self, client, registration):
        resp = client.get(f'/payments/success?order_id=REG-{registration.id}')
        assert resp.status_code in (302, 401)

    def test_invalid_order_id_redirects(self, client, user):
        _login(client, user)
        resp = client.get('/payments/success?order_id=INVALID')
        assert resp.status_code == 302

    def test_other_users_registration_returns_404(self, client, registration):
        other = User(email=f'other-{_uid()}@test.com', first_name='O', last_name='U')
        other.set_password('password123')
        db.session.add(other)
        db.session.flush()
        _login(client, other)
        resp = client.get(f'/payments/success?order_id=REG-{registration.id}')
        assert resp.status_code == 404


class TestFailurePage:
    def test_unauthenticated_redirects(self, client):
        resp = client.get('/payments/failure?order_id=REG-1')
        assert resp.status_code in (302, 401)

    def test_renders_without_order_id(self, client, user):
        _login(client, user)
        resp = client.get('/payments/failure')
        assert resp.status_code == 200

    def test_renders_with_valid_order_id(self, client, user, registration):
        _login(client, user)
        resp = client.get(f'/payments/failure?order_id=REG-{registration.id}')
        assert resp.status_code == 200
