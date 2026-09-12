"""Tests for app.services.partner_auth."""
import time
from uuid import uuid4

import jwt
import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services.partner_auth import (
    PrefillTokenError,
    decode_prefill_token,
    get_or_create_partner_user,
)


SECRET = 'test-secret-long-enough-for-hs256-xxxxxxxxxxxxxx'


@pytest.fixture
def enabled_partner(app):
    s = SiteSettings.get()
    s.partner_integration_enabled = True
    s.partner_prefill_secret = SECRET
    db.session.commit()
    yield s
    s.partner_integration_enabled = False
    s.partner_prefill_secret = ''
    db.session.commit()


def _token(claims, secret=SECRET):
    return jwt.encode(claims, secret, algorithm='HS256')


def _base_claims(**overrides):
    claims = {
        'iss': 'mm-medic',
        'email': f'user-{uuid4().hex[:6]}@example.com',
        'first_name': 'Ivan',
        'last_name': 'Petrenko',
        'phone': '+380670000000',
        'exp': int(time.time()) + 300,
    }
    claims.update(overrides)
    return claims


class TestDecodePrefillToken:
    def test_valid_token(self, enabled_partner):
        claims = _base_claims()
        payload = decode_prefill_token(_token(claims))
        assert payload.email == claims['email']
        assert payload.first_name == 'Ivan'
        assert payload.issuer == 'mm-medic'

    def test_rejects_expired(self, enabled_partner):
        claims = _base_claims(exp=int(time.time()) - 10)
        with pytest.raises(PrefillTokenError, match='expired'):
            decode_prefill_token(_token(claims))

    def test_rejects_wrong_signature(self, enabled_partner):
        with pytest.raises(PrefillTokenError):
            decode_prefill_token(_token(_base_claims(), secret='wrong-secret'))

    def test_rejects_unknown_issuer(self, enabled_partner):
        with pytest.raises(PrefillTokenError, match='issuer'):
            decode_prefill_token(_token(_base_claims(iss='evil-site')))

    def test_rejects_when_integration_disabled(self, app):
        s = SiteSettings.get()
        s.partner_integration_enabled = False
        s.partner_prefill_secret = SECRET
        db.session.commit()
        with pytest.raises(PrefillTokenError, match='disabled'):
            decode_prefill_token(_token(_base_claims()))

    def test_rejects_empty_token(self, enabled_partner):
        with pytest.raises(PrefillTokenError, match='Missing'):
            decode_prefill_token('')

    def test_rejects_missing_email(self, enabled_partner):
        claims = _base_claims()
        claims.pop('email')
        with pytest.raises(PrefillTokenError):
            decode_prefill_token(_token(claims))

    def test_rejects_malformed_email(self, enabled_partner):
        with pytest.raises(PrefillTokenError, match='email'):
            decode_prefill_token(_token(_base_claims(email='not-an-email')))

    def test_normalizes_email_to_lowercase(self, enabled_partner):
        claims = _base_claims(email='User@Example.COM')
        payload = decode_prefill_token(_token(claims))
        assert payload.email == 'user@example.com'


class TestGetOrCreatePartnerUser:
    def test_creates_new_user_with_confirmed_email(self, app):
        from app.services.partner_auth import PrefillPayload
        payload = PrefillPayload(
            email=f'new-{uuid4().hex[:6]}@example.com',
            first_name='Нова', last_name='Людина', phone='+380000',
            issuer='mm-medic',
        )
        user = get_or_create_partner_user(payload)
        assert user.id is not None
        assert user.email_confirmed is True
        assert user.first_name == 'Нова'

    def test_reuses_existing_user(self, app):
        from app.services.partner_auth import PrefillPayload
        email = f'existing-{uuid4().hex[:6]}@example.com'
        u = User(email=email, password='abcdefgh', first_name='Old')
        db.session.add(u)
        db.session.commit()

        payload = PrefillPayload(
            email=email, first_name='Ignored', last_name='X',
            phone=None, issuer='mm-medic',
        )
        user = get_or_create_partner_user(payload)
        assert user.id == u.id
        assert user.first_name == 'Old'  # not overwritten

    def test_confirms_email_on_partner_link(self, app):
        from app.services.partner_auth import PrefillPayload
        email = f'unconfirmed-{uuid4().hex[:6]}@example.com'
        u = User(email=email, password='x' * 10)
        u.email_confirmed = False
        db.session.add(u)
        db.session.commit()

        payload = PrefillPayload(
            email=email, first_name=None, last_name=None, phone=None,
            issuer='mm-medic',
        )
        get_or_create_partner_user(payload)
        db.session.refresh(u)
        assert u.email_confirmed is True


class TestPartnerUserProvisioning:
    """Партнерський акаунт не вигадує пароля і несе маркер джерела.

    Доти get_or_create_partner_user ставив secrets.token_urlsafe(32): акаунт
    виглядав як такий, що має пароль, хоча його не знав ніхто. Наслідок --
    людина не могла ні увійти, ні встановити пароль у кабінеті (сторінка
    відшивала з "Пароль уже встановлено"), а форма реєстрації казала лише
    невиразне "неможливо використати цей email".
    """

    def _payload(self, email=None, issuer='mm-medic'):
        from app.services.partner_auth import PrefillPayload
        return PrefillPayload(
            email=email or f'partner-{uuid4().hex[:6]}@example.com',
            first_name='Анатолій', last_name='Луньов',
            phone='+380670000000', issuer=issuer,
        )

    def test_new_partner_user_has_no_password(self, app):
        user = get_or_create_partner_user(self._payload())
        assert user.has_password is False

    def test_new_partner_user_is_marked_with_issuer(self, app):
        from app.models.auth_identity import AuthIdentity
        user = get_or_create_partner_user(self._payload())
        ident = AuthIdentity.query.filter_by(
            user_id=user.id, provider=AuthIdentity.PROVIDER_PARTNER,
        ).first()
        assert ident is not None
        assert ident.raw_claims['issuer'] == 'mm-medic'

    def test_repeat_prefill_does_not_duplicate_marker(self, app):
        from app.models.auth_identity import AuthIdentity
        payload = self._payload()
        user = get_or_create_partner_user(payload)
        get_or_create_partner_user(payload)
        assert AuthIdentity.query.filter_by(
            user_id=user.id, provider=AuthIdentity.PROVIDER_PARTNER,
        ).count() == 1

    def test_two_partner_users_coexist(self, app):
        """UNIQUE(provider, provider_sub) не має падати на другому партнері."""
        first = get_or_create_partner_user(self._payload())
        second = get_or_create_partner_user(self._payload())
        assert first.id != second.id

    def test_existing_password_account_keeps_its_password(self, app):
        """Реальний акаунт із паролем партнерський лінк не роззброює."""
        email = f'has-pw-{uuid4().hex[:6]}@example.com'
        user = User.create_with_password(email=email, password='realpassword')
        db.session.commit()
        get_or_create_partner_user(self._payload(email=email))
        assert user.has_password is True
