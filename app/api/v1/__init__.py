from flask import Blueprint

api_v1_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

from app.api.v1 import events  # noqa: E402,F401 — register routes
