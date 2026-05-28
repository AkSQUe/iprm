"""Google OAuth 2.0 service (Phase 3 of auth unification).

Тонкий wrapper навколо Authlib's OAuth flask client. Реєструє Google як
provider динамічно на основі SiteSettings (client_id/secret з адмінки),
а не з config -- щоб адмін міг змінити ключі без перезапуску сервера.

Discovery URL Google -- стандартний OIDC well-known endpoint, що містить
endpoints (authorize, token, userinfo, jwks) і автоматично оновлюється
Authlib-ом.

Викликати `init_oauth(app)` у фабриці додатку. У роутах -- `get_google_client()`
повертає OAuth client для startauth/callback flows.
"""
import logging
from authlib.integrations.flask_client import OAuth

logger = logging.getLogger(__name__)

# Google OIDC discovery (відповідає OAuth 2.0 + OpenID Connect). Authlib
# автоматично читає authorization_endpoint, token_endpoint, jwks_uri.
GOOGLE_DISCOVERY_URL = 'https://accounts.google.com/.well-known/openid-configuration'

_oauth = OAuth()


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
