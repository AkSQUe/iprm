import hashlib
import logging
import os
import time

from flask import Flask
from flask_cors import CORS
from config import config
from app.extensions import db, login_manager, csrf, migrate, limiter, mail, babel


_cached_assets_version = None


def get_assets_version(static_folder):
    global _cached_assets_version
    if _cached_assets_version:
        return _cached_assets_version

    css_dir = os.path.join(static_folder, 'css')
    js_dir = os.path.join(static_folder, 'js')
    mtimes = []

    for folder in (css_dir, js_dir):
        if os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.endswith(('.css', '.js')):
                    mtimes.append(f'{f}:{os.path.getmtime(os.path.join(folder, f))}')

    _cached_assets_version = (
        hashlib.md5('|'.join(mtimes).encode()).hexdigest()[:8] if mtimes else '1.0'
    )
    return _cached_assets_version


def _configure_logging(app):
    log_level = logging.DEBUG if app.debug else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
    ))
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(log_level)
    logging.getLogger('app').setLevel(log_level)


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])
    _configure_logging(app)

    if config_name == 'production':
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_prefix=0)

    if hasattr(config[config_name], 'init_app'):
        config[config_name].init_app(app)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    from app.i18n import get_locale, init_locale_routing
    babel.init_app(app, locale_selector=get_locale)
    init_locale_routing(app)

    # Authlib OAuth (Phase 3+): провайдери реєструються ліниво у
    # get_google_client()/get_apple_client(), щоб client_id/secret
    # підтягувалися з SiteSettings (DB-first) без рестарту.
    from app.services.google_oauth import init_oauth
    init_oauth(app)
    from app.services.apple_signin import init_apple_oauth
    init_apple_oauth(app)

    from flask_babel import lazy_gettext as _l
    login_manager.login_view = 'auth.login'
    login_manager.login_message = _l('Будь ласка, увійдіть для доступу до цієї сторінки.')
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

    from app.blog import blog_bp
    app.register_blueprint(blog_bp)

    from app.media import media_bp
    app.register_blueprint(media_bp)

    from app.services.error_handler import init_error_handlers
    init_error_handlers(app)

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
    app.register_blueprint(payments_bp)

    from app.api.v1 import api_v1_bp
    app.register_blueprint(api_v1_bp)

    from app.api.mm_status import mm_status_bp
    app.register_blueprint(mm_status_bp)
    csrf.exempt(mm_status_bp)
    _partner_origins = [
        o.strip() for o in os.environ.get(
            'PARTNER_CORS_ORIGINS',
            'https://mm-medic.com,https://www.mm-medic.com',
        ).split(',') if o.strip()
    ]
    CORS(
        app,
        resources={r'/api/v1/*': {'origins': _partner_origins}},
        methods=['GET', 'OPTIONS'],
        allow_headers=['X-API-Key', 'Content-Type'],
        max_age=3600,
    )

    from app.cli import seed_courses, media_prune_orphans, backup_group
    app.cli.add_command(seed_courses)
    app.cli.add_command(media_prune_orphans)
    app.cli.add_command(backup_group)

    @app.context_processor
    def inject_assets_version():
        if app.debug:
            version = str(int(time.time()))
        else:
            version = get_assets_version(app.static_folder)
        return {'assets_version': version}

    from app.utils import sanitize_rich_text, uk_plural
    app.jinja_env.filters['sanitize_rich_text'] = sanitize_rich_text
    app.jinja_env.filters['uk_plural'] = uk_plural

    # Глобал icon('<name>') -- рендерить Material Symbols іконку через кодпойнт
    # (self-hosted субсет-шрифт). Див. app/icons.py.
    from app.icons import render_icon, ICON_CODEPOINTS
    app.jinja_env.globals['icon'] = render_icon
    # Мапа назва->кодпойнт для JS-редакторів (blog-editor.js,
    # admin-trainer-regalia.js), які рендерять іконки динамічно через
    # window.msGlyph. Субсет-шрифт без лігатур, тож JS теж має слати кодпойнт.
    app.jinja_env.globals['icon_codepoints'] = ICON_CODEPOINTS

    # Словник i18n-рядків для публічних JS: рендериться у base.html як JSON
    # (#iprm-i18n-data) і читається js/i18n.js (window.iprmI18n.t).
    from app.js_strings import js_translations
    app.jinja_env.globals['js_translations'] = js_translations

    import re as _re
    # Лише правдоподібні роки (19xx/20xx), щоб не плутати інші 4-значні числа.
    _YEAR_RE = _re.compile(
        r'^\s*((?:19|20)\d{2}(?:\s*[–—-]\s*(?:19|20)\d{2})?(?:\s*р\.?)?)\s*[.—–-]*\s*(.*)$'
    )

    @app.template_filter('timeline_split')
    def _timeline_split(line):
        """Рядок -> {year, text}: виділяє провідний рік/діапазон у бейдж."""
        m = _YEAR_RE.match(line or '')
        if m and m.group(2).strip():
            return {'year': m.group(1).strip(), 'text': m.group(2).strip()}
        return {'year': '', 'text': (line or '').strip()}

    @app.before_request
    def preload_site_settings():
        from flask import g
        from app.models.site_settings import SiteSettings
        g.site_settings = SiteSettings.get()

    @app.context_processor
    def inject_site_settings():
        from flask import g
        from app.models.site_settings import SiteSettings
        # g.site_settings заповнюється @app.before_request для HTTP-запитів;
        # для background-render (scheduler, thread) g пустий -- підвантажуємо напряму.
        settings = getattr(g, 'site_settings', None)
        if settings is None:
            settings = SiteSettings.get()
        return {'site_settings': settings}

    @app.context_processor
    def inject_recaptcha():
        """Експозиція reCAPTCHA-сервісу в шаблони (для _recaptcha.html partial
        у <head> та можливих умовних рендерів). Сервіс легкий -- ні мережі,
        ні шифрування на read-only properties."""
        from app.services.recaptcha import get_recaptcha_service
        return {'recaptcha': get_recaptcha_service()}

    @app.context_processor
    def inject_upcoming_events():
        """Два найближчі майбутні заходи для плаваючого блоку на ПУБЛІЧНИХ
        сторінках (вмикається в Налаштуваннях сайту). Порожньо, якщо вимкнено,
        на /admin, або заходів немає."""
        from flask import g, request, url_for
        try:
            settings = getattr(g, 'site_settings', None)
            if settings is None or not getattr(settings, 'show_upcoming_events', False):
                return {'upcoming_events': []}
            path = request.path or ''
            if path.startswith('/admin') or path.startswith('/static'):
                return {'upcoming_events': []}
            from datetime import datetime, timezone
            from app.models.course_instance import CourseInstance
            now = datetime.now(timezone.utc)
            rows = (
                CourseInstance.query
                .filter(CourseInstance.status.in_(('published', 'active')))
                .filter(CourseInstance.start_date.isnot(None))
                .filter(CourseInstance.start_date >= now)
                .order_by(CourseInstance.start_date.asc())
                .limit(2).all()
            )
            events = []
            for inst in rows:
                course = inst.course
                if not course:
                    continue
                place = (inst.location or '').strip()
                if not place and inst.event_format == 'online':
                    from flask_babel import gettext
                    place = gettext('Онлайн')
                events.append({
                    'id': inst.id,
                    'title': course.t('title'),
                    'url': url_for('courses.course_by_slug', slug=course.slug),
                    'when': inst.start_date.strftime('%d.%m.%Y, %H:%M'),
                    'place': place,
                })
            return {'upcoming_events': events}
        except Exception:
            return {'upcoming_events': []}

    @app.context_processor
    def inject_certdata_reminder():
        """Сигналізатори "заповніть дані для сертифіката" (МОЗ №725 п.13)
        для авторизованого користувача з активною реєстрацією і незаповненою
        анкетою:

        - certdata_incomplete -- індикатор-тултіп біля імені в header
          (усі публічні сторінки);
        - show_certdata_reminder -- плаваючий pop-up; додатково вимкнений
          у кабінеті (там власний банер і сама анкета) та у флоу
          реєстрації/оплати, щоб не відволікати. Закриття -- sessionStorage.
        """
        from flask import request
        from flask_login import current_user
        flags = {'certdata_incomplete': False, 'show_certdata_reminder': False}
        try:
            if not current_user.is_authenticated:
                return flags
            path = request.path or ''
            if path.startswith('/admin') or path.startswith('/static'):
                return flags
            profile = current_user.medical_profile
            if profile and profile.is_complete:
                return flags
            from app.extensions import db
            from app.models.registration import EventRegistration
            has_reg = db.session.query(EventRegistration.id).filter(
                EventRegistration.user_id == current_user.id,
                EventRegistration.status != 'cancelled',
            ).first() is not None
            flags['certdata_incomplete'] = has_reg
            flags['show_certdata_reminder'] = has_reg and not (
                path.startswith('/auth') or path.startswith('/registration')
            )
            return flags
        except Exception:
            return flags

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['X-XSS-Protection'] = '1; mode=block'

        # reCAPTCHA-v3 потребує script-src/frame-src/connect-src для Google,
        # тому розширюємо CSP лише коли інтеграція active (інакше -- зайва дірка).
        from app.services.recaptcha import get_recaptcha_service
        try:
            recaptcha_active = get_recaptcha_service().is_active
        except Exception:
            recaptcha_active = False
        gstatic = ' https://www.google.com https://www.gstatic.com' if recaptcha_active else ''
        gframe = ' https://www.google.com' if recaptcha_active else ''
        gconn = ' https://www.google.com' if recaptcha_active else ''

        # Google Analytics 4 (gtag.js): домени додаємо лише коли GA увімкнено
        # (інакше gtag.js і маяки збору даних блокуються CSP -> нуль даних у GA).
        from flask import g
        ga_active = False
        gsi_active = False
        try:
            settings = getattr(g, 'site_settings', None)
            if settings is None:
                from app.models.site_settings import SiteSettings
                settings = SiteSettings.get()
            ga_active = bool(settings.effective_google_analytics_id)
            # Google One Tap (GSI) вставляє gsi/client лише коли OAuth налаштовано.
            gsi_active = settings.is_google_oauth_configured
        except Exception:
            pass
        ga_script = ' https://www.googletagmanager.com' if ga_active else ''
        ga_img = (' https://www.googletagmanager.com https://www.google-analytics.com'
                  ' https://*.google-analytics.com') if ga_active else ''
        ga_conn = (' https://www.googletagmanager.com https://www.google-analytics.com'
                   ' https://*.google-analytics.com https://*.analytics.google.com') if ga_active else ''

        # Google One Tap / Sign-In (GSI): script + style + frame + connect з
        # accounts.google.com, аватарки -- з googleusercontent.
        gsi = ' https://accounts.google.com' if gsi_active else ''
        gsi_img = ' https://*.googleusercontent.com' if gsi_active else ''

        # MM Medic: зображення товарів у резервуванні матеріалів вантажаться з
        # хосту MM Medic -- додаємо його origin до img-src лише коли інтеграція
        # активна (інакше зайва дірка в CSP).
        mm_img = ''
        try:
            if settings is not None and getattr(settings, 'mm_medic_integration_enabled', False):
                base = (settings.mm_medic_api_base_url or '').strip()
                if base:
                    from urllib.parse import urlparse
                    parsed = urlparse(base)
                    if parsed.scheme and parsed.netloc:
                        mm_img = f' {parsed.scheme}://{parsed.netloc}'
        except Exception:
            pass

        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'" + gstatic + ga_script + gsi + "; "
            "style-src 'self' 'unsafe-inline'" + gsi + "; "
            "font-src 'self' data:; "
            "img-src 'self' data:" + ga_img + gsi_img + mm_img + "; "
            "frame-src 'self' blob: https://www.liqpay.ua https://checkout.liqpay.ua"
            " https://www.youtube-nocookie.com"
            + gframe + gsi + "; "
            "connect-src 'self'" + gconn + ga_conn + gsi
        )
        response.headers['Content-Security-Policy'] = csp
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    @app.after_request
    def no_cache_html(response):
        if 'text/html' in (response.content_type or ''):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    @app.after_request
    def capture_referral(response):
        # Єдиний обробник ref-візиту: cookie + серверний pending + клік,
        # з одним читанням SiteSettings і одним commit.
        from flask import request
        from flask_login import current_user
        from app.services import referral_service
        try:
            return referral_service.capture_referral_visit(request, response, current_user)
        except Exception:
            logging.getLogger(__name__).exception('referral capture failed')
            return response

    from app.services.scheduler_service import init_scheduler
    init_scheduler(app)

    # Register SQLAlchemy listeners that fire partner webhooks on Course
    # and CourseInstance {insert,update,delete}. Best-effort — failures
    # are logged, not raised.
    from app.services.course_webhook_listener import register_course_listeners
    register_course_listeners(db)

    return app
