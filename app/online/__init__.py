from app.i18n import LocalizedBlueprint

online_bp = LocalizedBlueprint('online', __name__, url_prefix='/online-courses')

from app.online import routes  # noqa: F401,E402
