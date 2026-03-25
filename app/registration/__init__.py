from flask import Blueprint

registration_bp = Blueprint('registration', __name__, url_prefix='/registration')


@registration_bp.after_request
def add_noindex_header(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


from app.registration import routes  # noqa: F401,E402
