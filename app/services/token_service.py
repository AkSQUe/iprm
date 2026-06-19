"""Token generation and validation for email confirmation."""
import logging
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

logger = logging.getLogger(__name__)

SALT = 'email-confirm'
DEFAULT_MAX_AGE = 86400  # 24 години

# Скидання пароля: окрема сіль (щоб confirm-токен не годився як reset-токен)
# і коротший термін дії.
RESET_SALT = 'password-reset'
RESET_MAX_AGE = 3600  # 1 година


def _get_serializer(app=None):
    from flask import current_app
    secret = (app or current_app).config['SECRET_KEY']
    return URLSafeTimedSerializer(secret)


def generate_confirmation_token(user_id, app=None):
    s = _get_serializer(app)
    return s.dumps(user_id, salt=SALT)


def confirm_token(token, max_age=DEFAULT_MAX_AGE, app=None):
    s = _get_serializer(app)
    try:
        user_id = s.loads(token, salt=SALT, max_age=max_age)
        return user_id
    except SignatureExpired:
        logger.warning('Email confirmation token expired')
        return None
    except BadSignature:
        logger.warning('Email confirmation token invalid')
        return None


def generate_password_reset_token(user_id, app=None):
    s = _get_serializer(app)
    return s.dumps(user_id, salt=RESET_SALT)


def confirm_password_reset_token(token, max_age=RESET_MAX_AGE, app=None):
    s = _get_serializer(app)
    try:
        return s.loads(token, salt=RESET_SALT, max_age=max_age)
    except SignatureExpired:
        logger.warning('Password reset token expired')
        return None
    except BadSignature:
        logger.warning('Password reset token invalid')
        return None
