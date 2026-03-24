import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///iprm.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STATIC_URL_PATH = '/static'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = 1209600  # 14 days in seconds

    LIQPAY_PUBLIC_KEY = os.environ.get('LIQPAY_PUBLIC_KEY', '')
    LIQPAY_PRIVATE_KEY = os.environ.get('LIQPAY_PRIVATE_KEY', '')
    LIQPAY_SANDBOX = os.environ.get('LIQPAY_SANDBOX', 'true').lower() == 'true'


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = 'https'
    SEND_FILE_MAX_AGE_DEFAULT = 31536000
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
        'max_overflow': 20,
    }

    @staticmethod
    def init_app(app):
        secret = app.config.get('SECRET_KEY', '')
        if not secret or secret == 'dev-secret-key-change-in-production':
            raise RuntimeError('SECRET_KEY environment variable must be set for production')
        if len(secret) < 32:
            raise RuntimeError('SECRET_KEY must be at least 32 characters')


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}
