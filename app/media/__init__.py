from flask import Blueprint

media_bp = Blueprint('media', __name__)

from app.media import routes  # noqa: F401,E402
