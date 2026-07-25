"""Tests for auth routes -- email confirmation flow."""
import re

import pytest
from uuid import uuid4

from app.extensions import db
from app.models.user import User
from app.services.token_service import generate_confirmation_token


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def user(app):
    u = User.create_with_password(
        f'auth-{_uid()}@test.com', 'password123', first_name='Test', last_name='User',
    )
    db.session.flush()
    return u


def _flashes(resp):
    r"""Тексти flash-повідомлень зі сторінки.

    base.html віддає їх JSON-ом у <script id="iprm-flash-data"> (ui-feedback.js
    робить із них toasts), а |tojson екранує кирилицю у \uXXXX -- тож шукати
    підрядок у сирому HTML не можна."""
    import json
    match = re.search(
        r'<script type="application/json" id="iprm-flash-data">(.*?)</script>',
        resp.data.decode(), re.S,
    )
    if not match:
        return []
    return [item['message'] for item in json.loads(match.group(1))]


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


class TestPasswordLogin:
    """Вхід з паролем: identity-first, стан акаунта, повідомлення."""

    def test_valid_credentials_log_in(self, client, user):
        resp = client.post('/auth/login', data={
            'email': user.email, 'password': 'password123',
        })
        assert resp.status_code == 302
        assert '/account' in resp.headers.get('Location', '')
        with client.session_transaction() as sess:
            assert sess.get('_user_id') == str(user.id)

    def test_wrong_password_rejected(self, client, user):
        resp = client.post('/auth/login', data={
            'email': user.email, 'password': 'wrong-password',
        })
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get('_user_id') is None

    def test_inactive_account_gets_explicit_message(self, client, user):
        """Раніше login_user() мовчки відмовляв (повертав False), і юзера
        кидало на /auth/account -> @login_required -> назад на логін."""
        user.is_active = False
        db.session.flush()
        resp = client.post('/auth/login', data={
            'email': user.email, 'password': 'password123',
        })
        assert resp.status_code == 200
        assert any('деактивовано' in m for m in _flashes(resp))
        with client.session_transaction() as sess:
            assert sess.get('_user_id') is None

    def test_unknown_email_does_not_leak_existence(self, client):
        resp = client.post('/auth/login', data={
            'email': f'nobody-{_uid()}@test.com', 'password': 'password123',
        })
        assert resp.status_code == 200
        assert any('Невірний email або пароль' in m for m in _flashes(resp))

    def test_last_used_at_updated_on_login(self, client, user):
        from app.models.auth_identity import AuthIdentity
        ident = AuthIdentity.find_password_identity_by_email(user.email)
        assert ident.last_used_at is None
        client.post('/auth/login', data={
            'email': user.email, 'password': 'password123',
        })
        db.session.refresh(ident)
        assert ident.last_used_at is not None


class TestSetPassword:
    """Встановлення пароля для акаунта, що входив лише через OAuth."""

    def _oauth_only_user(self):
        from app.models.auth_identity import AuthIdentity
        u = User.create_with_oauth(
            provider=AuthIdentity.PROVIDER_GOOGLE, sub=_uid(),
            email=f'oauth-only-{_uid()}@test.com', email_verified=True,
        )
        db.session.flush()
        return u

    def test_requires_login(self, client):
        resp = client.get('/auth/account/set-password')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers.get('Location', '')

    def test_oauth_only_user_can_set_password(self, client):
        user = self._oauth_only_user()
        _login(client, user)
        resp = client.post('/auth/account/set-password', data={
            'password': 'brand-new-pass', 'password_confirm': 'brand-new-pass',
        })
        assert resp.status_code == 302
        assert '/connections' in resp.headers.get('Location', '')
        assert user.check_password('brand-new-pass')

    def test_user_with_password_is_redirected(self, client, user):
        _login(client, user)
        resp = client.get('/auth/account/set-password')
        assert resp.status_code == 302
        assert '/connections' in resp.headers.get('Location', '')

    def test_mismatched_confirmation_rejected(self, client):
        user = self._oauth_only_user()
        _login(client, user)
        resp = client.post('/auth/account/set-password', data={
            'password': 'brand-new-pass', 'password_confirm': 'other-pass',
        })
        assert resp.status_code == 200
        assert not user.check_password('brand-new-pass')


class TestConnectionsDiscoverable:
    """Сторінка «Способи входу» має бути досяжною з кабінету -- інакше
    інструкція на collision-сторінці нездійсненна."""

    def test_account_page_links_to_connections(self, client, user):
        _login(client, user)
        assert '/auth/account/connections' in client.get('/auth/account').data.decode()

    def test_connections_page_renders(self, client, user):
        _login(client, user)
        resp = client.get('/auth/account/connections')
        assert resp.status_code == 200
        assert user.email.encode() in resp.data
