import os
from dotenv import load_dotenv

load_dotenv()


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
    #
    # Прапорець потрібен окремо від ID (як у Meta й PostHog): ID сам собою
    # трекінг не вмикає, а стирання ID не є вимиканням -- порожнє поле в
    # адмінці означає "взяти з env". Прапорець у БД перекриває цю змінну в
    # обидва боки, тож аварійний рубильник діє й на проді, де ID з env.
    GOOGLE_ANALYTICS_ENABLED = os.environ.get(
        'GOOGLE_ANALYTICS_ENABLED', 'false').lower() == 'true'
    GOOGLE_ANALYTICS_ID = os.environ.get('GOOGLE_ANALYTICS_ID', '')

    # Meta (Facebook) Pixel -- fallback на env, якщо в БД (SiteSettings) пусто.
    # На відміну від GA тут потрібні обидві змінні: ID сам собою трекінг не
    # вмикає. Дефолт вимкнено -- щоб dev/test не слали конверсії у прод-кабінет
    # Meta (там вони псують навчання алгоритму, а видалити події не можна).
    META_PIXEL_ENABLED = os.environ.get('META_PIXEL_ENABLED', 'false').lower() == 'true'
    META_PIXEL_ID = os.environ.get('META_PIXEL_ID', '')

    # PostHog -- fallback на env, якщо в БД (SiteSettings) пусто. Як і Meta,
    # потрібні обидві змінні: ключ сам собою трекінг не вмикає. Дефолт
    # вимкнено, щоб dev/test не слали події у прод-проєкт (на відміну від
    # Meta, події тут видаляються, але статистику вони псують однаково).
    POSTHOG_ENABLED = os.environ.get('POSTHOG_ENABLED', 'false').lower() == 'true'
    POSTHOG_PROJECT_API_KEY = os.environ.get('POSTHOG_PROJECT_API_KEY', '')
    POSTHOG_SESSION_RECORDING = os.environ.get(
        'POSTHOG_SESSION_RECORDING', 'false').lower() == 'true'
    # Прибрати адмінку з-під збору цілком. Окремо від iprm_section: та
    # властивість дає фільтр у звітах, але події все одно доходять і
    # витрачають квоту.
    POSTHOG_EXCLUDE_ADMIN = os.environ.get(
        'POSTHOG_EXCLUDE_ADMIN', 'false').lower() == 'true'

    # Шлях first-party проксі (nginx) і адреса самого кабінету PostHog.
    #
    # api_host -- ВЛАСНИЙ шлях, не домен PostHog: nginx проксує його на
    # eu.i.posthog.com, тож для блокувальників запити виглядають
    # first-party. ui_host потрібен окремо -- без нього тулбар і плеєр
    # записів не працюють, бо SDK не знає, де живе сам кабінет.
    #
    # Префікс навмисно непрозорий: дока PostHog застерігає від '/posthog',
    # '/ph', '/analytics' -- блокувальники ловлять їх за назвою.
    POSTHOG_API_HOST = os.environ.get('POSTHOG_API_HOST', '/ngx-e')
    POSTHOG_UI_HOST = os.environ.get('POSTHOG_UI_HOST', 'https://eu.posthog.com')

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
    # Дефолт true зберігає поточну поведінку проду: GA працює доти, доки
    # адмін свідомо не зніме галку. Вимкнення -- дія в адмінці (вона йде в
    # audit-лог), а не тиха правка конфіга.
    GOOGLE_ANALYTICS_ENABLED = os.environ.get(
        'GOOGLE_ANALYTICS_ENABLED', 'true').lower() == 'true'
    GOOGLE_ANALYTICS_ID = os.environ.get('GOOGLE_ANALYTICS_ID', 'G-T2LHJ436ZG')
    # Проєкт "IPRM" (id 255460) на EU Cloud. Ключ phc_* публічний -- він і так
    # їде у HTML кожної сторінки, тож тут йому не гірше, ніж GA-шному G-*.
    # Реплей вмикається окремою змінною: увімкнути його -- рішення власника
    # про медданi, а не дефолт деплою.
    POSTHOG_ENABLED = os.environ.get('POSTHOG_ENABLED', 'true').lower() == 'true'
    POSTHOG_PROJECT_API_KEY = os.environ.get(
        'POSTHOG_PROJECT_API_KEY', 'phc_wi73dtG77zD6oQua7i8xFERD9CYDqHYac9xcRBvEMKof')
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
