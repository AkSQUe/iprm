from app.i18n import LocalizedBlueprint

trainers_bp = LocalizedBlueprint('trainers', __name__, url_prefix='/trainers')

from app.trainers import routes
