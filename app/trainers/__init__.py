from flask import Blueprint

trainers_bp = Blueprint('trainers', __name__, url_prefix='/trainers')

from app.trainers import routes
