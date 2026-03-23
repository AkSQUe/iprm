from flask import Blueprint

courses_bp = Blueprint('courses', __name__, url_prefix='/courses')

from app.courses import routes
