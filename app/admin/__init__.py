from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.after_request
def add_noindex_header(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


from app.admin import routes  # noqa: F401,E402
