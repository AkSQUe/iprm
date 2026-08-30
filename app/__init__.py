import hashlib
import logging
import os
import time

from flask import Flask, request, url_for
from flask_cors import CORS
from config import config
from app.extensions import db, login_manager, csrf, migrate, limiter, mail, babel


_cached_assets_version = None

# Блюпринти, де плаваючий поп-ап "заповніть дані для сертифіката" зайвий: у
# кабінеті вже є власний банер і сама анкета, а у флоу реєстрації, оплати й
# тестування поп-ап поверх форми -- лише шум. Порівнюємо назву блюпринта, а не
# префікс шляху: auth/registration/quiz локалізовані, тож у ru/en їхні шляхи
# починаються з /ru або /en (див. inject_certdata_reminder).
_CERTDATA_POPUP_MUTED = frozenset({'auth', 'registration', 'payments', 'quiz'})


def get_assets_version(static_folder):
    """Ключ ?v= для CSS/JS -- хеш ВМІСТУ файлів, а не їхніх mtime.

    Раніше рахувались mtime, і це зривало кеш на кожному деплої: rsync
    оновлює час модифікації й тим файлам, вміст яких не змінився. Статика
    віддається з `max-age=2592000, immutable`, тож кожен повторний відвідувач
    після кожного деплою наново тягнув усі CSS і JS. За вмістом ключ міняється
    лише тоді, коли щось справді змінилось.

    133 файли / 1.2 МБ читаються один раз на першому запиті й лягають у кеш
    процесу, тож на подальші запити це не впливає.
    """
    global _cached_assets_version
    if _cached_assets_version:
        return _cached_assets_version

    digest = hashlib.md5()
    seen = False

    for folder in (os.path.join(static_folder, 'css'),
                   os.path.join(static_folder, 'js')):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(('.css', '.js')):
                continue
            try:
                with open(os.path.join(folder, name), 'rb') as fh:
                    digest.update(name.encode())
                    for chunk in iter(lambda: fh.read(65536), b''):
                        digest.update(chunk)
            except OSError:
                # Файл міг зникнути просто під rsync-деплоєм. Пропускаємо:
                # менш точний ключ кешу краще за 500 на всьому сайті.
                continue
            seen = True

    _cached_assets_version = digest.hexdigest()[:8] if seen else '1.0'
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

    from app.online import online_bp
    app.register_blueprint(online_bp)

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

    from app.quiz import quiz_bp
    app.register_blueprint(quiz_bp)

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

    from app.api.meta_leads import meta_leads_bp
    app.register_blueprint(meta_leads_bp)
    csrf.exempt(meta_leads_bp)

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

    from app.cli import (
        seed_courses, seed_plazmogel, seed_course_gallery, media_prune_orphans,
        backup_group, legal_docx, meta_reemit_leads,
    )
    app.cli.add_command(seed_courses)
    app.cli.add_command(seed_plazmogel)
    app.cli.add_command(seed_course_gallery)
    app.cli.add_command(media_prune_orphans)
    app.cli.add_command(backup_group)
    app.cli.add_command(legal_docx)
    app.cli.add_command(meta_reemit_leads)

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
    # Локалізована плюралізація (uk/ru/en) для публічних сторінок; uk_plural
    # лишається для uk-only PDF-сертифікатів.
    from app.i18n_plurals import plural
    app.jinja_env.filters['plural'] = plural
    # Назва локації розкладу активною мовою через довідник City. Канонічна
    # укр-назва лишається в CourseInstance.location -- фільтр застосовуємо
    # лише там, де текст читає людина (не в JSON-LD, ICS і партнерському API).
    from app.services.city_glossary import localize_location
    app.jinja_env.filters['localize_location'] = localize_location
    # Суми: `| int` округлював 0.60 до 0, і лист про залишок після промокоду
    # показував "0 UAH". Копійки друкуємо лише коли вони є.
    from app.services.money import format_amount, money
    app.jinja_env.filters['money'] = money
    app.jinja_env.filters['amount'] = format_amount

    # Час у київській зоні. Колонки timezone=True лежать у UTC, і `strftime`
    # без переведення друкував їх на три години раніше -- нічне замовлення
    # виглядало вчорашнім. Решта адмінських шаблонів досі друкує UTC: перехід
    # робиться посторінково, бо частина полів -- `date`, а частина вже
    # київська (`_listing.now_kyiv`).
    from app.utils import kyiv_dt
    app.jinja_env.filters['kyiv'] = kyiv_dt

    # Дані перекладів для інлайн мовних вкладок в адмін-формах
    # (partials/_i18n_tabs.html). Єдине джерело -- translation_registry.
    from app.services.translation_registry import (
        coverage as tr_coverage, coverage_label as tr_coverage_label,
        field_status as tr_field_status, inline_leaves as tr_inline_leaves,
        orphaned as tr_orphaned,
    )
    app.jinja_env.globals['tr_coverage'] = tr_coverage
    app.jinja_env.globals['tr_coverage_label'] = tr_coverage_label
    app.jinja_env.globals['tr_field_status'] = tr_field_status
    app.jinja_env.globals['tr_inline_leaves'] = tr_inline_leaves
    app.jinja_env.globals['tr_orphaned'] = tr_orphaned

    # Глобал icon('<name>') -- рендерить Material Symbols іконку через кодпойнт
    # (self-hosted субсет-шрифт). Див. app/icons.py.
    from app.icons import render_icon, ICON_CODEPOINTS
    app.jinja_env.globals['icon'] = render_icon
    # Мапа назва->кодпойнт для JS-редакторів (blog-editor.js,
    # admin-trainer-regalia.js), які рендерять іконки динамічно через
    # window.msGlyph. Субсет-шрифт без лігатур, тож JS теж має слати кодпойнт.
    app.jinja_env.globals['icon_codepoints'] = ICON_CODEPOINTS

    # Абсолютний URL для структурованих даних: Google не приймає у JSON-LD
    # відносний шлях, а MediaFile.url віддає саме такий (/media/...).
    # None на порожньому вході, щоб виклик не треба було обгортати в {% if %}.
    def _abs_url(path):
        if not path:
            return None
        if path.startswith(('http://', 'https://')):
            return path
        return request.url_root.rstrip('/') + '/' + path.lstrip('/')

    app.jinja_env.globals['abs_url'] = _abs_url

    # @id організації в JSON-LD -- ОДИН на весь сайт, незалежно від локалі.
    #
    # Доти, доки він будувався з url_for('main.index', _external=True), його
    # значення йшло за активною мовою: '/#org' на українській, '/ru/#org' на
    # російській, '/en/#org' на англійській. Для Google @id -- це
    # ідентичність сутності, тож одна компанія оголошувалась ТРЬОМА
    # різними організаціями, а provider курсу з /ru/ вказував на третю з
    # них. lang_code=DEFAULT_LANGUAGE фіксує безпрефіксний корінь
    # мови-джерела: url_for з явним lang_code обирає правило з defaults і
    # віддає '/' у будь-якій локалі (префікс підставляє url_defaults-хук
    # лише тоді, коли lang_code не переданий).
    #
    # Значення саме '<корінь>#org' -- дослівно те, що вже стояло в
    # українському рендері, тож посилання provider/publisher і сторожі, які
    # звіряють ці рядки посимвольно, лишаються чинними.
    from app.i18n import DEFAULT_LANGUAGE as _DEFAULT_LANGUAGE

    def _org_id():
        return url_for(
            'main.index', lang_code=_DEFAULT_LANGUAGE, _external=True,
        ) + '#org'

    app.jinja_env.globals['org_id'] = _org_id

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
    def inject_undo_offer():
        """Пропозиція відкату останньої дії -- тост із кнопкою "Повернути".

        Забираємо з сесії один раз за запит: якщо той самий запит рендерить
        ще й лист, перший рендер з'їв би пропозицію, і сторінка лишилась би
        без тоста. Токен додаємо тут: кнопка відкату шле POST.

        Кеш живе на request, а НЕ на g: під зовнішнім app-контекстом (тести,
        скрипти) g спільний для кількох запитів, і закешоване "пропозиції
        немає" перекрило б наступні.
        """
        from flask import has_request_context, request
        from app.undo import pop_undo
        # Листи рендеряться у фоновому потоці, де немає ні сесії, ні CSRF.
        if not has_request_context():
            return {'undo_offer': None}
        offer = getattr(request, '_undo_offer', Ellipsis)
        if offer is Ellipsis:
            offer = pop_undo()
            if offer:
                from flask_wtf.csrf import generate_csrf
                offer = {**offer, 'csrf': generate_csrf()}
            request._undo_offer = offer
        return {'undo_offer': offer}

    @app.context_processor
    def inject_recaptcha():
        """Експозиція reCAPTCHA-сервісу в шаблони (для _recaptcha.html partial
        у <head> та можливих умовних рендерів). Сервіс легкий -- ні мережі,
        ні шифрування на read-only properties."""
        from app.services.recaptcha import get_recaptcha_service
        return {'recaptcha': get_recaptcha_service()}

    @app.context_processor
    def inject_meta_pixel():
        """ID активного Meta Pixel для _meta_pixel.html і підключення
        meta-events.js. Через сервіс, а не властивість налаштувань напряму:
        рішення залежить ще й від блупринту (в адмінці трекінгу немає), і
        воно мусить збігатися з тим, що дозволяє CSP."""
        from app.services.meta_pixel import active_pixel_id
        return {'meta_pixel_id': active_pixel_id()}

    @app.context_processor
    def inject_posthog():
        """Конфіг активного PostHog для _posthog.html і підключення
        analytics-events.js. Через сервіс, а не властивість налаштувань
        напряму: рішення залежить ще й від блупринту (розділ у подіях,
        глибина маскування реплею), і воно мусить збігатися з тим, що
        дозволяє CSP."""
        from app.services.posthog import active_posthog_config
        return {'posthog_config': active_posthog_config()}

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
          у кабінеті (там власний банер і сама анкета), у флоу
          реєстрації/оплати та у тестуванні (там гейт сам каже, чого
          бракує, а поверх питань поп-ап -- лише шум).
          Закриття -- sessionStorage.

        Винятки визначаємо по НАЗВІ БЛЮПРИНТА, а не по префіксу шляху. Раніше
        стояло `path.startswith('/quiz')`, і для ru/en це не спрацьовувало
        ніколи: `auth`, `registration` і `quiz` -- LocalizedBlueprint, тобто
        реальний шлях у них `/ru/quiz/5`. Російсько- й англомовний учасник
        отримував поп-ап поверх питань тесту, а в кабінеті -- поп-ап разом із
        власним банером і самою анкетою. Той самий ідіом уже вживає
        `cache_control_html` нижче.
        """
        from flask import request
        from flask_login import current_user
        flags = {'certdata_incomplete': False, 'show_certdata_reminder': False}
        try:
            if not current_user.is_authenticated:
                return flags
            if request.blueprint == 'admin':
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
            flags['show_certdata_reminder'] = has_reg and (
                request.blueprint not in _CERTDATA_POPUP_MUTED
            )
            return flags
        except Exception:
            return flags

    class _SkipIntegrationCsp(Exception):
        """Сентинел: на не-HTML відповідях інтеграції не опитуємо."""

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['X-XSS-Protection'] = '1; mode=block'

        # Дозволи для сторонніх доменів рахуємо ЛИШЕ для HTML: скрипти
        # виконуються в документі, а цей хук спрацьовує на кожну відповідь --
        # включно з JSON API, редиректами і файлами. Для них політика
        # лишається базовою, тобто СТРОГІШОЮ, а не слабшою: сторонні домени
        # просто не додаються.
        #
        # Сама структура CSP нижче не змінюється -- інакше PDF-відповіді
        # (сертифікати, рахунки) могли б втратити 'self' і перестати
        # відкриватись у вбудованому переглядачі.
        is_html = (response.mimetype or '').startswith('text/html')

        gstatic = gframe = gconn = ''
        recaptcha_active = False
        if is_html:
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
        pixel_active = False
        posthog_cfg = None
        settings = None
        try:
            if not is_html:
                raise _SkipIntegrationCsp
            settings = getattr(g, 'site_settings', None)
            if settings is None:
                from app.models.site_settings import SiteSettings
                settings = SiteSettings.get()
            ga_active = bool(settings.effective_google_analytics_id)
            # Google One Tap (GSI) вставляє gsi/client лише коли OAuth налаштовано.
            gsi_active = settings.is_google_oauth_configured
            # Через сервіс, а не властивість: та сама умова, що вирішує
            # вставку скрипта. Інакше CSP дозволяв би домени Meta в адмінці,
            # де скрипта немає.
            from app.services.meta_pixel import active_pixel_id
            pixel_active = bool(active_pixel_id(settings))
            # Через той самий сервіс, що вирішує вставку скрипта -- інакше
            # CSP світив би worker-src blob: на сторінках без PostHog.
            from app.services.posthog import active_posthog_config
            posthog_cfg = active_posthog_config(settings)
        except Exception:
            pass
        ga_script = ' https://www.googletagmanager.com' if ga_active else ''
        ga_img = (' https://www.googletagmanager.com https://www.google-analytics.com'
                  ' https://*.google-analytics.com') if ga_active else ''
        ga_conn = (' https://www.googletagmanager.com https://www.google-analytics.com'
                   ' https://*.google-analytics.com https://*.analytics.google.com') if ga_active else ''

        # Meta Pixel: fbevents.js вантажиться з connect.facebook.net, а самі
        # події йдуть маяками на facebook.com. Домени -- лише коли Pixel
        # активний (той самий мотив, що з GA: без них -- нуль даних, з ними
        # завжди -- зайва дірка).
        px_script = ' https://connect.facebook.net' if pixel_active else ''
        px_img = ' https://www.facebook.com' if pixel_active else ''
        px_conn = ' https://www.facebook.com https://connect.facebook.net' if pixel_active else ''

        # PostHog: увесь трафік іде на власний домен (nginx проксує /ngx-e/ на
        # eu.i.posthog.com), тож 'self' покриває і SDK, і збір подій -- зайвих
        # доменів у script-src/connect-src не треба.
        #
        # А от worker-src потрібен окремо: запис сесій стискає дані у Web
        # Worker, створеному з blob:. Директиви worker-src у політиці немає,
        # тож вона впала б на default-src 'self', і реплей мовчки не
        # запрацював би -- помилка видна лише в консолі браузера відвідувача.
        #
        # ui_host додаємо в script-src/connect-src заради тулбара: він
        # вантажиться з самого кабінету PostHog, а не через проксі.
        ph_worker = ''
        ph_script = ''
        ph_conn = ''
        if posthog_cfg:
            ph_worker = " worker-src 'self' blob:; "
            ui_host = posthog_cfg.get('ui_host') or ''
            if ui_host.startswith('https://'):
                ph_script = f' {ui_host}'
                ph_conn = f' {ui_host}'

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
            # Два хости віджета оплати LiqPay (див. docs/integrations/liqpay.md):
            #   static.liqpay.ua      -- сама бібліотека checkout.js;
            #   applepay.cdn-apple.com -- Apple Pay SDK, який checkout.js
            #     довантажує В НАШУ сторінку (ApplePaySession працює лише в
            #     верхньому документі, тому не в їхньому iframe).
            # Без другого Apple Pay мовчки не працює: у їхньому коді
            # script.onerror лише резолвить проміс, тож віджет піднімається
            # без помилки, а обіцяний на сторінці спосіб оплати зникає.
            "script-src 'self' 'unsafe-inline' https://static.liqpay.ua"
            " https://applepay.cdn-apple.com"
            + gstatic + ga_script + gsi + px_script + ph_script + "; "
            "style-src 'self' 'unsafe-inline'" + gsi + "; "
            "font-src 'self' data:; "
            "img-src 'self' data:" + ga_img + gsi_img + mm_img + px_img + "; "
            "frame-src 'self' blob: https://www.liqpay.ua https://checkout.liqpay.ua"
            " https://www.youtube-nocookie.com"
            + gframe + gsi + "; "
            + ph_worker +
            "connect-src 'self'" + gconn + ga_conn + gsi + px_conn + ph_conn
        )
        response.headers['Content-Security-Policy'] = csp
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # Блупринти, чий HTML може містити приватні дані або одноразовий стан
    # (кабінет, адмінка, форми реєстрації на захід, оплати). Для них лишається
    # no-store.
    PRIVATE_HTML_BLUEPRINTS = frozenset({
        'auth', 'admin', 'registration', 'payments', 'quiz',
    })

    # Окремі приватні сторінки в публічному блупринті. Каталог онлайн-курсів
    # анонімний і має лишатись придатним для bfcache, а от чекаут і сторінка
    # гостьового замовлення показують чужу покупку тому, хто ще не залогінений
    # -- саме той випадок, заради якого `registration` цілком у списку вище.
    PRIVATE_HTML_ENDPOINTS = frozenset({
        'online.checkout', 'online.order', 'online.order_set_password',
    })

    @app.after_request
    def cache_control_html(response):
        """Кеш-політика HTML.

        `no-store` -- єдина директива, що вимикає bfcache у Chrome, тож
        навігація "назад" щоразу перезавантажувала сторінку (на мобільному це
        секунди). Лишаємо її тільки там, де у HTML можуть бути приватні дані:
        автентифіковані відповіді та приватні блупринти. Публічні сторінки для
        анонімів отримують `private, no-cache` -- браузер зобовʼязаний
        ревалідувати перед показом (свіжість не втрачаємо), але сторінка
        лишається придатною для bfcache.
        """
        if 'text/html' not in (response.content_type or ''):
            return response
        from flask import request
        from flask_login import current_user
        private = (request.blueprint in PRIVATE_HTML_BLUEPRINTS
                   or request.endpoint in PRIVATE_HTML_ENDPOINTS)
        if not private:
            try:
                private = current_user.is_authenticated
            except Exception:
                private = True
        response.headers['Cache-Control'] = (
            'no-store, no-cache, must-revalidate' if private else 'private, no-cache'
        )
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

    # Реєстрації учасників — партнеру, у ту саму чергу доставок. Слухачі на
    # моделі, а не виклики в роутах: реєстрація створюється трьома шляхами, а
    # оплата змінюється ще й LiqPay-колбеком.
    from app.services.partner_events import register_registration_listeners
    register_registration_listeners(db)

    return app
