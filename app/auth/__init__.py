from app.i18n import LocalizedBlueprint

auth_bp = LocalizedBlueprint('auth', __name__, url_prefix='/auth')


@auth_bp.after_request
def add_noindex_header(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


from app.auth import routes  # noqa: F401,E402
from app.auth import oauth   # noqa: F401,E402
from app.auth import routes_refunds  # noqa: F401,E402
