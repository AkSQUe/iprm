import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///iprm.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STATIC_URL_PATH = '/static'
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB (фото із заходів, HEIC з iPhone)
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'static', 'images')
    # Generated certificate PDFs. Stored OUTSIDE app/static (private documents
    # served only through an auth-gated route). Kept at project root and
    # excluded from rsync --delete (see .github/workflows/deploy.yml) so issued
    # certificates persist across deploys. Override with CERTIFICATE_FOLDER env.
    CERTIFICATE_FOLDER = os.environ.get('CERTIFICATE_FOLDER') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'certificates',
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = 1209600  # 14 days in seconds

    LIQPAY_PUBLIC_KEY = os.environ.get('LIQPAY_PUBLIC_KEY', '')
    LIQPAY_PRIVATE_KEY = os.environ.get('LIQPAY_PRIVATE_KEY', '')
    LIQPAY_SANDBOX = os.environ.get('LIQPAY_SANDBOX', 'true').lower() == 'true'

    # reCAPTCHA v3 -- fallback на env, якщо в БД (SiteSettings) пусто.
    # RECAPTCHA_ENABLED = 'true' активує перевірку (за наявності ключів).
    RECAPTCHA_ENABLED = os.environ.get('RECAPTCHA_ENABLED', 'false').lower() == 'true'
    RECAPTCHA_SITE_KEY = os.environ.get('RECAPTCHA_SITE_KEY', '')
    RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY', '')
    RECAPTCHA_SCORE_THRESHOLD = float(os.environ.get('RECAPTCHA_SCORE_THRESHOLD', '0.5'))

    # Google Analytics 4 Measurement ID (публічний; вшитий у HTML на кожній
    # сторінці). Порожній рядок -- GA вимкнено. Дефолт у базі -- порожній,
    # щоб dev/test не слали події у прод-аналітику. ProductionConfig
    # переозначає реальний ID.
    GOOGLE_ANALYTICS_ID = os.environ.get('GOOGLE_ANALYTICS_ID', '')

    # Блог: розмір сторінки лістингу та ліміт RSS-стрічки (тюнінг без коду).
    BLOG_POSTS_PER_PAGE = int(os.environ.get('BLOG_POSTS_PER_PAGE', '9'))
    BLOG_FEED_LIMIT = int(os.environ.get('BLOG_FEED_LIMIT', '20'))

    # Flask-Limiter: бекенд сховища лімітів. In-memory не спільний між
    # gunicorn-воркерами (ліміти множаться) -- у проді задайте RATELIMIT_STORAGE_URI
    # (напр. redis://127.0.0.1:6379). Порожньо -> memory:// (dev).
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')

    # Mail -- налаштування зберігаються в БД (EmailSettings),
    # Flask-Mail ініціалізується з дефолтами, потім перевизначається через apply_to_app()
    MAIL_SUPPRESS_SEND = True  # Вимкнено за замовчуванням, вмикається через адмінку


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = 'https'
    SEND_FILE_MAX_AGE_DEFAULT = 31536000
    GOOGLE_ANALYTICS_ID = os.environ.get('GOOGLE_ANALYTICS_ID', 'G-T2LHJ436ZG')
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
