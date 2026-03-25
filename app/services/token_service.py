"""Token generation and validation for email confirmation."""
import logging
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

logger = logging.getLogger(__name__)

SALT = 'email-confirm'
DEFAULT_MAX_AGE = 86400  # 24 години


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
