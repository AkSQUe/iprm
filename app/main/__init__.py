from app.i18n import LocalizedBlueprint

main_bp = LocalizedBlueprint('main', __name__)

from app.main import routes
