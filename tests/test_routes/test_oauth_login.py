"""Tests for OAuth login resolution -- Google redirect-flow і One Tap.

Головне, що перевіряємо: вхід через Google для юзера, який УЖЕ є в базі.
Раніше будь-який збіг email завершувався сторінкою-колізією (або, для
імпортованих юзерів без identity, падінням на UNIQUE(users.email)) --
тобто вхід через Google не спрацьовував узагалі.
"""
import pytest
from uuid import uuid4
from unittest.mock import patch

from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.user import User


def _email():
    return f'oauth-{uuid4().hex[:10]}@gmail.com'


TEST_NONCE = 'test-onetap-nonce'


def _claims(email, sub=None, verified=True):
    return {
        'sub': sub or uuid4().hex,
        'email': email,
        'email_verified': verified,
        'given_name': 'Test',
        'family_name': 'User',
    }


@pytest.fixture
def google_configured(app):
    """Вмикає Google OAuth, не підміняючи весь SiteSettings: сторінки
    рендеряться зі справжніми налаштуваннями (recaptcha, бренд тощо)."""
    from app.models.site_settings import SiteSettings
    with patch.object(
        SiteSettings, 'is_google_oauth_configured', property(lambda self: True),
    ):
        yield


@pytest.fixture(autouse=True)
def _fresh_rate_limit(app):
    """One Tap лімітований 20 запитами на годину, а лічильник у пам'яті
    спільний на весь прогін: з ростом файлу останні тести починали
    отримувати 429 і падати з неочевидним "юзер не залогінився"."""
    from app.extensions import limiter
    limiter.reset()
    yield


def _prime_nonce(client, nonce=TEST_NONCE):
    """Покласти nonce у сесію так, як це робить рендер віджета."""
    from app.auth.oauth import SESSION_ONETAP_NONCE
    with client.session_transaction() as sess:
        sess[SESSION_ONETAP_NONCE] = nonce


def _onetap(client, claims, prime_nonce=True):
    """POST /auth/google/onetap із замоканою верифікацією JWT.

    Верифікацію мокаємо цілком (підпис Google не відтворити в тестах),
    тож nonce перевіряємо окремо -- через аргумент, з яким її викликали.
    """
    if prime_nonce:
        _prime_nonce(client)
    with patch('app.auth.oauth.verify_google_id_token', return_value=claims):
        return client.post('/auth/google/onetap', json={'credential': 'fake.jwt.token'})


def _is_logged_in(client, user):
    with client.session_transaction() as sess:
        return sess.get('_user_id') == str(user.id)


class TestOneTapNewUser:
    def test_creates_user_when_email_unknown(self, client, google_configured):
        email = _email()
        resp = _onetap(client, _claims(email))
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True

        user = User.query.filter_by(email=email).first()
        assert user is not None
        assert user.email_confirmed
        assert _is_logged_in(client, user)


class TestOneTapExistingUser:
    def test_links_to_imported_user_without_identity(self, client, google_configured):
        """1200+ імпортованих учасників не мають жодної identity. Раніше це
        падало на UNIQUE(users.email) -> 500."""
        email = _email()
        user = User(email=email, first_name='Imported')
        db.session.add(user)
        db.session.flush()

        resp = _onetap(client, _claims(email))
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True

        identity = AuthIdentity.query.filter_by(
            user_id=user.id, provider=AuthIdentity.PROVIDER_GOOGLE,
        ).first()
        assert identity is not None
        assert user.email_confirmed  # провайдер підтвердив володіння скринькою
        assert _is_logged_in(client, user)
        # Новий User не створювався -- прив'язались до наявного.
        assert User.query.filter_by(email=email).count() == 1

    def test_links_to_password_user_with_confirmed_email(self, client, google_configured):
        email = _email()
        user = User.create_with_password(email, 'password123', email_confirmed=True)
        db.session.flush()

        resp = _onetap(client, _claims(email))
        assert resp.status_code == 200
        assert _is_logged_in(client, user)
        assert AuthIdentity.query.filter_by(
            user_id=user.id, provider=AuthIdentity.PROVIDER_GOOGLE,
        ).first() is not None

    def test_second_login_reuses_identity(self, client, google_configured):
        email = _email()
        claims = _claims(email)
        assert _onetap(client, claims).status_code == 200
        user = User.query.filter_by(email=email).first()

        resp = _onetap(client, claims)
        assert resp.status_code == 200
        assert AuthIdentity.query.filter_by(
            provider=AuthIdentity.PROVIDER_GOOGLE, provider_sub=claims['sub'],
        ).count() == 1
        assert _is_logged_in(client, user)

    def test_inactive_user_rejected(self, client, google_configured):
        email = _email()
        user = User(email=email, is_active=False)
        db.session.add(user)
        db.session.flush()

        resp = _onetap(client, _claims(email))
        assert resp.status_code == 403
        assert resp.get_json()['error'] == 'inactive'


class TestOneTapCollision:
    """Pre-hijacking guard: пароль є, а email у нас НЕ підтверджений."""

    def test_unconfirmed_password_account_gets_collision_page(self, client, google_configured):
        email = _email()
        user = User.create_with_password(email, 'password123', email_confirmed=False)
        db.session.flush()

        resp = _onetap(client, _claims(email))
        assert resp.status_code == 409
        data = resp.get_json()
        assert data['error'] == 'email_collision'
        assert data['next'] == '/auth/oauth/collision'
        assert not _is_logged_in(client, user)

        # Сторінка-пояснення рендериться з контексту в сесії й одноразова.
        page = client.get(data['next'])
        assert page.status_code == 200
        assert email.encode() in page.data
        assert client.get(data['next']).status_code == 302

    def test_unverified_provider_email_never_auto_links(self, client, google_configured):
        """email_verified=false у claims -> прив'язки нема навіть до
        підтвердженого акаунта."""
        email = _email()
        User.create_with_password(email, 'password123', email_confirmed=True)
        db.session.flush()

        resp = _onetap(client, _claims(email, verified=False))
        assert resp.status_code == 409


class TestOneTapNonce:
    """Nonce прив'язує credential до сесії -- інакше будь-який валідний
    Google-токен логінив би жертву в чужий акаунт (login CSRF)."""

    def test_without_nonce_in_session_is_401(self, client, google_configured):
        resp = _onetap(client, _claims(_email()), prime_nonce=False)
        assert resp.status_code == 401
        assert resp.get_json()['error'] == 'invalid_credential'

    def test_session_nonce_passed_to_verification(self, client, google_configured):
        _prime_nonce(client)
        with patch('app.auth.oauth.verify_google_id_token',
                   return_value=_claims(_email())) as verify:
            client.post('/auth/google/onetap', json={'credential': 'fake.jwt'})
        assert verify.call_args.kwargs['expected_nonce'] == TEST_NONCE

    def test_widget_renders_nonce(self, client, google_configured):
        body = client.get('/').data.decode()
        assert 'data-nonce="' in body


class TestOneTapRace:
    """One Tap уміє дублювати виклики (у проді бачили 4 POST за 12 секунд).
    Паралельне створення того самого акаунта не має давати 500."""

    def test_duplicate_user_creation_falls_back_to_linking(self, client, google_configured):
        """Резолвер не знайшов User, але на вставці отримав UNIQUE-конфлікт:
        має перечитати акаунт і прив'язати identity до нього, а не 500.

        db.session.rollback() підміняємо no-op: у тестах сесія загорнута в
        зовнішню транзакцію (conftest), і справжній rollback знищив би
        "переможця гонки" разом із рештою даних тесту. Перевіряємо саме
        гілку except -> перечитування -> прив'язка.
        """
        from sqlalchemy.exc import IntegrityError
        email = _email()

        winner = User(email=email, email_confirmed=True)
        db.session.add(winner)
        db.session.flush()

        def losing_create(*args, **kwargs):
            raise IntegrityError('duplicate key value', None, Exception())

        with patch.object(User, 'create_with_oauth', losing_create), \
             patch('app.auth.oauth.User.query') as user_query, \
             patch.object(db.session, 'rollback'):
            # Перший lookup (до створення) -- порожньо, після конфлікту --
            # акаунт уже є. Саме так виглядає гонка з боку програвшого.
            user_query.filter_by.return_value.first.side_effect = [None, winner]
            resp = _onetap(client, _claims(email))

        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True
        assert AuthIdentity.query.filter_by(
            user_id=winner.id, provider=AuthIdentity.PROVIDER_GOOGLE,
        ).first() is not None

    def test_two_sequential_calls_same_sub_create_one_identity(self, client, google_configured):
        email = _email()
        claims = _claims(email)
        assert _onetap(client, claims).status_code == 200
        assert _onetap(client, claims).status_code == 200
        assert AuthIdentity.query.filter_by(
            provider=AuthIdentity.PROVIDER_GOOGLE, provider_sub=claims['sub'],
        ).count() == 1


class TestOneTapGuards:
    def test_missing_credential_is_400(self, client, google_configured):
        assert client.post('/auth/google/onetap', json={}).status_code == 400

    def test_invalid_credential_is_401(self, client, google_configured):
        _prime_nonce(client)
        with patch('app.auth.oauth.verify_google_id_token', side_effect=ValueError('bad')):
            resp = client.post('/auth/google/onetap', json={'credential': 'x'})
        assert resp.status_code == 401

    def test_keys_unavailable_is_503_not_401(self, client, google_configured):
        """Наш збій (не дістали JWKS) не має маскуватись під поганий токен."""
        from app.services.google_oauth import GoogleKeysUnavailable
        _prime_nonce(client)
        with patch('app.auth.oauth.verify_google_id_token',
                   side_effect=GoogleKeysUnavailable('down')):
            resp = client.post('/auth/google/onetap', json={'credential': 'x'})
        assert resp.status_code == 503
        assert resp.get_json()['error'] == 'keys_unavailable'

    def test_not_configured_is_503(self, client):
        """Без ключів у SiteSettings (дефолт у тестовій БД) -- 503."""
        resp = client.post('/auth/google/onetap', json={'credential': 'x'})
        assert resp.status_code == 503


class TestOneTapWidgetPlacement:
    """One Tap не має вантажитись на сторінках auth: його відповідь
    обривала redirect-флоу (nginx 499) і давала цикл редіректів."""

    def test_absent_on_login_page(self, client, google_configured):
        assert b'g_id_onload' not in client.get('/auth/login').data

    def test_present_on_public_page(self, client, google_configured):
        assert b'g_id_onload' in client.get('/').data


class TestLogoutClearsRememberCookie:
    """logout_user() cookie "remember me" сам НЕ стирає -- лише лишає в
    сесії позначку _remember='clear' для after_request Flask-Login.
    session.clear() у роуті з'їдав позначку, cookie переживав вихід і
    наступний запит логінив назад: тост "Ви вийшли" був, а юзер лишався."""

    def _remember_cookie(self, client):
        from flask_login.config import COOKIE_NAME
        return client.get_cookie(COOKIE_NAME)

    def test_logout_deletes_remember_cookie(self, client, google_configured):
        # One Tap логінить із remember=True -- саме так і виникає cookie
        assert _onetap(client, _claims(_email())).status_code == 200
        assert self._remember_cookie(client) is not None

        client.post('/auth/logout')
        assert self._remember_cookie(client) is None

    def test_user_stays_out_after_logout(self, client, google_configured):
        email = _email()
        _onetap(client, _claims(email))
        client.post('/auth/logout')

        # Наступний запит не має відновити вхід із cookie
        resp = client.get('/auth/account')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']
        user = User.query.filter_by(email=email).first()
        assert not _is_logged_in(client, user)


class TestOneTapAfterLogout:
    """Вихід зациклювався: після редіректу на "/" юзер уже анонімний, One
    Tap із auto_select=true мовчки віддавав credential і логінив назад --
    ззовні "натиснув Вийти, сторінка перезавантажилась, я досі в акаунті"."""

    def test_widget_suppressed_right_after_logout(self, client, google_configured):
        email = _email()
        assert _onetap(client, _claims(email)).status_code == 200
        user = User.query.filter_by(email=email).first()
        assert _is_logged_in(client, user)

        assert client.post('/auth/logout').status_code == 302
        assert not _is_logged_in(client, user)
        assert b'g_id_onload' not in client.get('/').data

    def test_deliberate_login_clears_the_flag(self, client, google_configured):
        email = _email()
        _onetap(client, _claims(email))
        client.post('/auth/logout')
        with client.session_transaction() as sess:
            assert sess.get('onetap_off') is True

        # Свідомий вхід знімає глушник: усі три шляхи входу (пароль, redirect
        # -флоу Google, One Tap) роблять session.clear() перед login_user.
        assert _onetap(client, _claims(email)).status_code == 200
        with client.session_transaction() as sess:
            assert 'onetap_off' not in sess


class TestRedirectFlowCollisionPage:
    def test_direct_hit_without_context_redirects_to_login(self, client):
        resp = client.get('/auth/oauth/collision')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']
