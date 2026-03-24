from flask import Blueprint

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')

from app.payments import routes  # noqa: F401,E402
