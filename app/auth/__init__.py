from flask import Blueprint

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.after_request
def add_noindex_header(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


from app.auth import routes  # noqa: F401,E402
