"""
Flask extensions are initialized here.

To avoid circular imports with blueprints and create_app(),
extensions are instantiated separately and initialized in create_app().
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
