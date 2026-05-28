"""Apple Sign In service (Phase 5 of auth unification).

Apple має нестандартний OAuth2-flow:
1) client_secret -- це короткий JWT, підписаний ES256 нашим .p8-ключем
   з developer.apple.com. Авторизаційний JWT має payload:
     iss: team_id (10 chars)
     iat: now
     exp: now + 30 days (max 6 months за специфікацією Apple)
     aud: 'https://appleid.apple.com'
     sub: services_id (bundle ID для web, напр. com.example.web)
   Header: {alg: ES256, kid: key_id}.
2) authorize-endpoint вимагає response_mode=form_post і scope='name email'.
   Apple POST-ить дані назад у наш callback (не GET, як Google).
3) name приходить ЛИШЕ при першому логіні у параметрі 'user'
   (JSON-encoded {name: {firstName, lastName}, email}). Треба
   обов'язково закешувати у raw_claims при першому login -- іншим разом
   ці дані Apple не передасть.
4) email може бути приватним relay-форматом xxx@privaterelay.appleid.com
   (Apple Hide My Email).

Authlib повторно реєструємо клієнта при кожному виклику get_apple_client(),
щоб підтягувати свіжі credentials і свіжий client_secret JWT.
"""
import logging
import time

import jwt as pyjwt
from authlib.integrations.flask_client import OAuth

logger = logging.getLogger(__name__)

APPLE_DISCOVERY_URL = 'https://appleid.apple.com/.well-known/openid-configuration'

# Apple дозволяє до 6 місяців; беремо 30 днів -- безпечніше при ротації ключів.
APPLE_CLIENT_SECRET_TTL_SECONDS = 60 * 60 * 24 * 30

_oauth = OAuth()


def init_apple_oauth(app):
    """Прив'язати Authlib OAuth instance до Flask-додатку. Реєстрація
    провайдера 'apple' -- ліниво у get_apple_client()."""
    _oauth.init_app(app)


def _generate_client_secret(team_id, services_id, key_id, private_key_pem):
    """Сгенерувати короткоживучий JWT для Apple client_secret.

    Приватний ключ .p8 -- PEM-блок з ECDSA P-256 ключем. PyJWT приймає
    PEM як string. Сигнатура ES256.
    """
    now = int(time.time())
    payload = {
        'iss': team_id,
        'iat': now,
        'exp': now + APPLE_CLIENT_SECRET_TTL_SECONDS,
        'aud': 'https://appleid.apple.com',
        'sub': services_id,
    }
    return pyjwt.encode(
        payload,
        private_key_pem,
        algorithm='ES256',
        headers={'kid': key_id},
    )


def get_apple_client():
    """Повертає сконфігурований OAuth-client для Apple. None, якщо
    Apple Sign In не налаштований у SiteSettings."""
    from app.models.site_settings import SiteSettings
    settings = SiteSettings.get()
    if not settings.is_apple_signin_configured:
        return None

    try:
        client_secret = _generate_client_secret(
            settings.apple_team_id,
            settings.apple_services_id,
            settings.apple_key_id,
            settings.apple_private_key,
        )
    except Exception:
        logger.exception('Failed to generate Apple client_secret JWT')
        return None

    # Перереєстрація з поточними credentials (як у google_oauth).
    if 'apple' in _oauth._clients:
        del _oauth._clients['apple']

    _oauth.register(
        name='apple',
        client_id=settings.apple_services_id,
        client_secret=client_secret,
        server_metadata_url=APPLE_DISCOVERY_URL,
        client_kwargs={
            'scope': 'name email',
            # Apple вимагає form_post для отримання name на першому логіні.
            'response_mode': 'form_post',
            'token_endpoint_auth_method': 'client_secret_post',
        },
    )
    return _oauth.apple
