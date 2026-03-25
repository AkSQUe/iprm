"""Tests for auth routes -- email confirmation flow."""
import pytest
from uuid import uuid4

from app.extensions import db
from app.models.user import User
from app.services.token_service import generate_confirmation_token


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def user(app):
    u = User(email=f'auth-{_uid()}@test.com', first_name='Test', last_name='User')
    u.set_password('password123')
    db.session.add(u)
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


class TestConfirmEmail:
    def test_valid_token_confirms_email(self, client, user):
        assert not user.email_confirmed
        token = generate_confirmation_token(user.id)
        resp = client.get(f'/auth/confirm/{token}')
        assert resp.status_code == 302
        db.session.refresh(user)
        assert user.email_confirmed

    def test_invalid_token_redirects_with_error(self, client):
        resp = client.get('/auth/confirm/invalid-token', follow_redirects=True)
        assert resp.status_code == 200

    def test_expired_token_rejected(self, client, user):
        import time
        token = generate_confirmation_token(user.id)
        time.sleep(1)
        from unittest.mock import patch
        with patch('app.auth.routes.confirm_token', return_value=None):
            resp = client.get(f'/auth/confirm/{token}')
            assert resp.status_code == 302
            db.session.refresh(user)
            assert not user.email_confirmed

    def test_already_confirmed_is_noop(self, client, user):
        user.email_confirmed = True
        db.session.flush()
        token = generate_confirmation_token(user.id)
        resp = client.get(f'/auth/confirm/{token}')
        assert resp.status_code == 302
        db.session.refresh(user)
        assert user.email_confirmed

    def test_authenticated_user_redirects_to_account(self, client, user):
        _login(client, user)
        token = generate_confirmation_token(user.id)
        resp = client.get(f'/auth/confirm/{token}')
        assert resp.status_code == 302
        assert '/account' in resp.headers.get('Location', '')


class TestResendConfirmation:
    def test_unauthenticated_redirects(self, client):
        resp = client.post('/auth/resend-confirmation')
        assert resp.status_code in (302, 401)

    def test_already_confirmed_skips(self, client, user):
        user.email_confirmed = True
        db.session.flush()
        _login(client, user)
        resp = client.post('/auth/resend-confirmation')
        assert resp.status_code == 302

    def test_resend_redirects_to_account(self, client, user):
        _login(client, user)
        resp = client.post('/auth/resend-confirmation')
        assert resp.status_code == 302
        assert '/account' in resp.headers.get('Location', '')
