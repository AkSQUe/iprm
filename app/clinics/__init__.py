from app.i18n import LocalizedBlueprint

clinics_bp = LocalizedBlueprint('clinics', __name__, url_prefix='/clinics')

from app.clinics import routes
