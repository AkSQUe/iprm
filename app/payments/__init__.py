from flask import Blueprint

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')


@payments_bp.after_request
def add_noindex_header(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


from app.payments import routes  # noqa: F401,E402
