from flask import Blueprint

registration_bp = Blueprint('registration', __name__, url_prefix='/registration')

from app.registration import routes  # noqa: F401,E402
