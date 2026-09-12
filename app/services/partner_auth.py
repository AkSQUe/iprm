"""Verify prefill JWTs issued by partner sites (MM Medic).

Flow:
- Partner site signs JWT with shared secret (HS256) containing user identity.
- IPRM verifies signature + expiration, then either logs in existing user
  or creates a new User with email_confirmed=True.

Security notes:
- Short TTL (5 min) is enforced by partner; iprm re-checks `exp` claim.
- No replay guard in MVP — impact of replay is bounded (same user opens same
  form with same prefilled data). Add DB-backed jti cache if threat model changes.
"""
import logging
from dataclasses import dataclass

import jwt

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.auth_identity import AuthIdentity
from app.models.user import User

logger = logging.getLogger(__name__)

ALLOWED_ISSUERS = {'mm-medic'}

# Як звати партнера в текстах для людей. Ключ -- issuer з prefill-токена.
ISSUER_LABELS = {'mm-medic': 'MM Medic'}


def issuer_label(issuer: str) -> str:
    """Людська назва партнера; невідомий issuer лишається як є."""
    return ISSUER_LABELS.get(issuer, issuer or '')


@dataclass(frozen=True)
class PrefillPayload:
    email: str
    first_name: str | None
    last_name: str | None
    phone: str | None
    issuer: str


class PrefillTokenError(Exception):
    """Raised when token is invalid, expired, or from untrusted issuer."""


def decode_prefill_token(token: str) -> PrefillPayload:
    """Verify JWT signature + claims. Raises PrefillTokenError on failure."""
    if not token or not isinstance(token, str):
        raise PrefillTokenError('Missing token')

    settings = SiteSettings.get()
    secret = settings.partner_prefill_secret
    if not settings.partner_integration_enabled or not secret:
        raise PrefillTokenError('Partner integration disabled')

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=['HS256'],
            options={'require': ['exp', 'iss', 'email']},
        )
    except jwt.ExpiredSignatureError as exc:
        raise PrefillTokenError('Token expired') from exc
    except jwt.InvalidTokenError as exc:
        raise PrefillTokenError(f'Invalid token: {exc}') from exc

    issuer = claims.get('iss')
    if issuer not in ALLOWED_ISSUERS:
        raise PrefillTokenError(f'Untrusted issuer: {issuer!r}')

    email = (claims.get('email') or '').strip().lower()
    if not email or '@' not in email:
        raise PrefillTokenError('Invalid email claim')

    return PrefillPayload(
        email=email,
        first_name=_clean(claims.get('first_name')),
        last_name=_clean(claims.get('last_name')),
        phone=_clean(claims.get('phone')),
        issuer=issuer,
    )


def get_or_create_partner_user(payload: PrefillPayload) -> User:
    """Return existing User by email or create one with email_confirmed=True.

    Partner-verified users skip email confirmation step since the partner site
    already authenticated them.
    """
    user = User.query.filter_by(email=payload.email).first()
    created = user is None
    if created:
        # Акаунт БЕЗ пароля -- як гість після покупки. Доти сюди ставили
        # secrets.token_urlsafe(32): акаунт виглядав як такий, що має
        # пароль, хоча його не знав ніхто, і людина не могла ні увійти,
        # ні встановити пароль у кабінеті.
        user = User.create_partner_linked(
            email=payload.email,
            issuer=payload.issuer,
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
    else:
        if not user.email_confirmed:
            user.email_confirmed = True
        # Маркер походження чіпляємо і до акаунтів, що існували раніше:
        # за ним форма реєстрації називає джерело.
        AuthIdentity.attach_partner(user, payload.issuer)

    db.session.commit()
    if created:
        logger.info(
            'Created partner-linked user id=%d email=%s from issuer=%s',
            user.id, user.email, payload.issuer,
        )
    return user


def _clean(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None
