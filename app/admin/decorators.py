from functools import wraps
from flask import abort
from flask_login import current_user

ADMIN_EMAILS = ['aksque@gmail.com']


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.email not in ADMIN_EMAILS:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function
