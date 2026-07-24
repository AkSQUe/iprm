from app.i18n import LocalizedBlueprint

courses_bp = LocalizedBlueprint('courses', __name__, url_prefix='/courses')

from app.courses import routes
