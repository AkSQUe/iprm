from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def create_app(config_name=None):
    import os
    from config import config

    app = Flask(__name__)

    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'default')
    app.config.from_object(config[config_name])

    db.init_app(app)

    from app.routes import main_bp
    app.register_blueprint(main_bp)

    return app
