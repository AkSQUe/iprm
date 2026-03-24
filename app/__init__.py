import os
from flask import Flask
from config import config
from app.extensions import db, login_manager, csrf, migrate, limiter


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    if hasattr(config[config_name], 'init_app'):
        config[config_name].init_app(app)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Будь ласка, увійдіть для доступу до цієї сторінки.'
    login_manager.login_message_category = 'info'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import User
        user = db.session.get(User, int(user_id))
        if user and user.is_active:
            return user
        return None

    from app import models  # noqa: F401 - ensure all models are loaded for Alembic

    from app.main import main_bp
    app.register_blueprint(main_bp)

    from app.courses import courses_bp
    app.register_blueprint(courses_bp)

    from app.errors import errors_bp
    app.register_blueprint(errors_bp)

    from app.auth import auth_bp
    app.register_blueprint(auth_bp)

    from app.admin import admin_bp
    app.register_blueprint(admin_bp)

    from app.registration import registration_bp
    app.register_blueprint(registration_bp)

    from app.trainers import trainers_bp
    app.register_blueprint(trainers_bp)

    from app.clinics import clinics_bp
    app.register_blueprint(clinics_bp)

    from app.payments import payments_bp
    csrf.exempt(payments_bp)
    app.register_blueprint(payments_bp)

    from app.cli import seed_courses
    app.cli.add_command(seed_courses)

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    return app
