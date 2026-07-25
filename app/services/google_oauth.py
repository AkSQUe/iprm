"""Google OAuth 2.0 service (Phase 3+6 of auth unification).

Тонкий wrapper навколо Authlib's OAuth flask client. Реєструє Google як
provider динамічно на основі SiteSettings (client_id/secret з адмінки),
а не з config -- щоб адмін міг змінити ключі без перезапуску сервера.

Discovery URL Google -- стандартний OIDC well-known endpoint, що містить
endpoints (authorize, token, userinfo, jwks) і автоматично оновлюється
Authlib-ом.

Викликати `init_oauth(app)` у фабриці додатку. У роутах --
`get_google_client()` повертає OAuth client для redirect-flow.

Phase 6 (One Tap): `verify_google_id_token()` верифікує id_token JWT, що
приходить з фронта через Google's GSI library. Перевіряє підпис проти
поточного JWKS Google, iss і aud claim-и.
"""
import logging
import time

import requests
from authlib.integrations.flask_client import OAuth
from authlib.jose import jwt as jose_jwt, JsonWebKey

logger = logging.getLogger(__name__)

# Google OIDC discovery (відповідає OAuth 2.0 + OpenID Connect). Authlib
# автоматично читає authorization_endpoint, token_endpoint, jwks_uri.
GOOGLE_DISCOVERY_URL = 'https://accounts.google.com/.well-known/openid-configuration'
GOOGLE_JWKS_URL = 'https://www.googleapis.com/oauth2/v3/certs'

# JWKS-кеш у пам'яті процесу. Google ротує ключі рідко (~раз на місяць);
# рефрешимо раз на годину.
_JWKS_CACHE = {'fetched_at': 0, 'key_set': None}
_JWKS_TTL_SECONDS = 3600

_oauth = OAuth()


class GoogleKeysUnavailable(RuntimeError):
    """Не вдалося дістати публічні ключі Google і немає навіть застарілого
    кешу. Це НАШ збій (мережа/Google), а не поганий токен -- caller має
    відповісти 503, а не 401."""


def init_oauth(app):
    """Прив'язати Authlib OAuth instance до Flask-додатку. Реєстрації
    провайдерів робимо ліниво (per-request), щоб підтягувати свіжий
    client_id/secret з БД."""
    _oauth.init_app(app)
    logger.debug('OAuth initialized for app')


def get_google_client():
    """Повертає сконфігурований OAuth client для Google. Реєструє провайдера
    "google" якщо ще не зареєстровано в поточному додатку. Підтягує
    client_id/secret зі SiteSettings (DB-first).

    Повертає None, якщо Google OAuth не сконфігуровано (вимкнено або
    немає ключів) -- caller має це обробити (показати "Не налаштовано").
    """
    from app.models.site_settings import SiteSettings
    settings = SiteSettings.get()

    if not settings.is_google_oauth_configured:
        return None

    # Authlib кешує реєстрацію по імені; перевіряємо чи треба перереєструвати
    # (наприклад після зміни ключів в адмінці). Простіше -- завжди
    # реєструємо з поточними значеннями. Authlib дозволяє overwrite.
    if 'google' in _oauth._clients:
        del _oauth._clients['google']

    _oauth.register(
        name='google',
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        server_metadata_url=GOOGLE_DISCOVERY_URL,
        client_kwargs={
            # Мінімально необхідні scope: openid (sub), email, profile (name).
            # Не запитуємо доступ до інших Google API.
            'scope': 'openid email profile',
        },
    )
    return _oauth.google


def _get_google_key_set():
    """Повертає JsonWebKey set з JWKS Google. Кешуємо у пам'яті процесу
    на годину, бо ключі ротуються рідко і HTTP-запит на кожен One Tap
    був би марнотратним.

    Якщо рефреш не вдався, віддаємо ПРОСТРОЧЕНИЙ кеш: ключі Google живуть
    значно довше за наш TTL, тож стара копія майже напевно ще валідна, і
    одна мережева помилка не кладе вхід через One Tap на годину.
    Кидає GoogleKeysUnavailable, лише коли кешу нема взагалі.
    """
    now = time.time()
    cached = _JWKS_CACHE['key_set']
    if cached is not None and now - _JWKS_CACHE['fetched_at'] < _JWKS_TTL_SECONDS:
        return cached

    try:
        resp = requests.get(GOOGLE_JWKS_URL, timeout=5)
        resp.raise_for_status()
        key_set = JsonWebKey.import_key_set(resp.json())
    except Exception as exc:
        if cached is not None:
            logger.warning(
                'Google JWKS refresh failed (%s); using stale cache from %.0fs ago',
                exc, now - _JWKS_CACHE['fetched_at'],
            )
            return cached
        raise GoogleKeysUnavailable('Google JWKS fetch failed') from exc

    _JWKS_CACHE['key_set'] = key_set
    _JWKS_CACHE['fetched_at'] = now
    return key_set


def verify_google_id_token(token, expected_audience, expected_nonce=None):
    """Phase 6: верифікація id_token JWT від Google One Tap.

    Перевіряємо:
    - підпис проти поточного JWKS Google;
    - iss == accounts.google.com (або https://accounts.google.com);
    - aud == наш OAuth client_id;
    - nonce == той, що ми поклали у віджет (прив'язка до сесії; захист
      від login CSRF) -- якщо expected_nonce передано;
    - exp/nbf (виконує claims.validate()).

    Повертає dict з claims (sub, email, email_verified, given_name, etc.).
    Кидає GoogleKeysUnavailable при недоступності ключів і виключення
    Authlib при невалідному токені -- caller розрізняє ці випадки.
    """
    key_set = _get_google_key_set()
    claims_options = {
        'iss': {
            'essential': True,
            'values': ['https://accounts.google.com', 'accounts.google.com'],
        },
        'aud': {'essential': True, 'value': expected_audience},
    }
    if expected_nonce:
        claims_options['nonce'] = {'essential': True, 'value': expected_nonce}
    claims = jose_jwt.decode(token, key_set, claims_options=claims_options)
    claims.validate()  # перевіряє exp, nbf
    return dict(claims)
