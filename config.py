import os
from dotenv import load_dotenv

# Guarded: tests/test_config_dev_database.py reloads this module per case
# via importlib.reload() to recompute class-level SQLALCHEMY_DATABASE_URI
# from a monkeypatched os.environ. An unguarded load_dotenv() re-reads .env
# on every reload and repopulates keys the test deliberately deleted
# (override=False only protects keys still PRESENT in os.environ, not ones
# a test just removed), silently breaking the fallback-to-DATABASE_URL case.
if not os.environ.get('_DOTENV_LOADED'):
    load_dotenv()
    os.environ['_DOTENV_LOADED'] = '1'


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # i18n (Flask-Babel). Українська -- вихідна мова коду й шаблонів, тому
    # каталог перекладів існує лише для ru/en (див. app/translations/ і
    # docs/i18n.md). Порядок вибору локалі -- app/i18n.py:get_locale().
    LANGUAGES = ['uk', 'ru', 'en']
    BABEL_DEFAULT_LOCALE = 'uk'
    BABEL_DEFAULT_TIMEZONE = 'Europe/Kyiv'
    BABEL_TRANSLATION_DIRECTORIES = 'translations'
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
    # Медіа-реєстр (MediaFile). Зберігається ПОЗА app/static -- щоб деплой
    # (rsync --delete) не зачіпав завантаження. На проді віддається nginx-alias
    # (/media/ -> {root}/media/), у dev/fallback -- Flask-роутом media.serve.
    # Кореневу теку виключено з rsync (як /certificates/). Override -- MEDIA_FOLDER.
    MEDIA_FOLDER = os.environ.get('MEDIA_FOLDER') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'media',
    )
    MEDIA_URL_PREFIX = '/media'
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

    # Meta (Facebook) Pixel -- fallback на env, якщо в БД (SiteSettings) пусто.
    # На відміну від GA тут потрібні обидві змінні: ID сам собою трекінг не
    # вмикає. Дефолт вимкнено -- щоб dev/test не слали конверсії у прод-кабінет
    # Meta (там вони псують навчання алгоритму, а видалити події не можна).
    META_PIXEL_ENABLED = os.environ.get('META_PIXEL_ENABLED', 'false').lower() == 'true'
    META_PIXEL_ID = os.environ.get('META_PIXEL_ID', '')

    # Блог: розмір сторінки лістингу та ліміт RSS-стрічки (тюнінг без коду).
    BLOG_POSTS_PER_PAGE = int(os.environ.get('BLOG_POSTS_PER_PAGE', '9'))
    BLOG_FEED_LIMIT = int(os.environ.get('BLOG_FEED_LIMIT', '20'))

    # Flask-Limiter: бекенд сховища лімітів. In-memory не спільний між
    # gunicorn-воркерами (ліміти множаться) -- у проді задайте RATELIMIT_STORAGE_URI
    # (напр. redis://127.0.0.1:6379). Порожньо -> memory:// (dev).
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')

    # CSRF: токен діє протягом сесії, а не фіксовану годину. Лишається
    # HMAC-підписаним і прив'язаним до сесії (безпечно), але не протермінову-
    # ється на сторінках, відкритих довго (напр. форма логауту -> 400 CSRF).
    WTF_CSRF_TIME_LIMIT = None

    # Mail -- налаштування зберігаються в БД (EmailSettings),
    # Flask-Mail ініціалізується з дефолтами, потім перевизначається через apply_to_app()
    MAIL_SUPPRESS_SEND = True  # Вимкнено за замовчуванням, вмикається через адмінку

    # Database backup settings
    BACKUP_STORAGE_PATH = os.environ.get('BACKUP_STORAGE_PATH') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'backups',
    )
    BACKUP_RETENTION_DAYS = int(os.environ.get('BACKUP_RETENTION_DAYS', '30'))
    BACKUP_OPERATION_TIMEOUT = int(os.environ.get('BACKUP_OPERATION_TIMEOUT', '3600'))
    BACKUP_MAX_CONCURRENT = int(os.environ.get('BACKUP_MAX_CONCURRENT', '1'))

    # Експорт юридичних сторінок у .docx (flask legal-docx)
    LEGAL_DOCX_LETTERHEAD = os.environ.get(
        'LEGAL_DOCX_LETTERHEAD', 'docs/legal/Шаблон листа ІПРМ.docx')
    LEGAL_DOCX_OUTPUT_DIR = os.environ.get('LEGAL_DOCX_OUTPUT_DIR', 'docs/legal')
    LEGAL_DOCX_SIGNER_TITLE = os.environ.get('LEGAL_DOCX_SIGNER_TITLE', 'Ректор')
    LEGAL_DOCX_SIGNER_NAME = os.environ.get(
        'LEGAL_DOCX_SIGNER_NAME', 'Заболотня Д. О.')


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    # Окрема база для розробки. Доти `DATABASE_URL` був один на все, і
    # будь-яка міграція вперше виконувалась у бойовій базі -- у проєкті без
    # dev-контуру це не необережність, а єдиний спосіб узагалі перевірити DDL.
    # Fallback на `DATABASE_URL` лишається свідомо: на машині без dev-бази
    # додаток має піднятись, а не впасти на імпорті конфігу.
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DATABASE_URL_DEV')
        or os.environ.get('DATABASE_URL', 'sqlite:///iprm.db')
    )


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
