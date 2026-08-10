import logging
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db

audit_logger = logging.getLogger('audit')
logger = logging.getLogger(__name__)


@admin_bp.route('/')
@admin_required
def dashboard():
    return redirect(url_for('admin.courses_list'))


# Довгі реєстри (сертифікати, користувачі) віддаємо сторінками.
_LIST_PER_PAGE = 50

_CERT_STATES = {'valid': 'Дійсні', 'revoked': 'Відкликані'}


def _certificate_filters():
    """Фільтри реєстру сертифікатів -- спільні для сторінки й експорту."""
    from app.admin import _listing
    return {
        'q': _listing.text_arg('q'),
        'state': _listing.choice_arg('state', _CERT_STATES),
        'course_id': _listing.int_arg('course_id'),
        'year': _listing.int_arg('year'),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _certificates_query(filters):
    """Сертифікати під фільтри, найновіші першими."""
    from sqlalchemy import extract
    from sqlalchemy.orm import joinedload
    from app.admin import _listing
    from app.models.certificate import Certificate
    from app.models.course_instance import CourseInstance
    from app.models.registration import EventRegistration
    from app.models.user import User

    query = Certificate.query.options(
        joinedload(Certificate.user),
        joinedload(Certificate.issued_by),
    )
    if filters['q']:
        # Номер і ПІБ -- знімки на самому сертифікаті; email живе в User,
        # тож приєднуємо власника (inner join безпечний: user_id NOT NULL).
        query = query.join(User, Certificate.user_id == User.id)
        query = _listing.apply_search(query, filters['q'], [
            Certificate.number, Certificate.recipient_name,
            Certificate.event_title, User.email,
        ])
    if filters['state']:
        query = query.filter(Certificate.revoked.is_(filters['state'] == 'revoked'))
    if filters['course_id']:
        # Курс живе через реєстрацію -> проведення (на сертифікаті лишився
        # лише текстовий знімок назви заходу).
        query = query.join(
            EventRegistration, Certificate.registration_id == EventRegistration.id,
        ).join(
            CourseInstance, EventRegistration.instance_id == CourseInstance.id,
        ).filter(CourseInstance.course_id == filters['course_id'])
    if filters['year']:
        query = query.filter(extract('year', Certificate.issued_at) == filters['year'])
    query = _listing.apply_date_range(
        query, Certificate.issued_at, filters['date_from'], filters['date_to'],
    )
    return query.order_by(Certificate.issued_at.desc())


def _certificate_stats():
    """Лічильники по ВСІХ сертифікатах: шапка не має стрибати від фільтра."""
    from sqlalchemy import case, func
    from app.models.certificate import Certificate

    total, revoked = db.session.query(
        func.count(Certificate.id),
        func.count(case((Certificate.revoked.is_(True), 1))),
    ).one()
    return {'total': total, 'active': total - revoked, 'revoked': revoked}


@admin_bp.route('/certificates')
@admin_required
def certificates():
    from sqlalchemy import extract
    from app.models.certificate import Certificate
    from app.models.course import Course

    filters = _certificate_filters()
    # Роки беремо з даних: порожній рік у списку -- пастка «фільтр нічого не
    # знайшов», а не вибір.
    years = sorted({
        int(y) for (y,) in db.session.query(
            extract('year', Certificate.issued_at),
        ).distinct().all() if y is not None
    }, reverse=True)
    # Реєстр росте після кожного заходу, тож сторінками; експорт лишається
    # по всьому зрізу -- пагінація це властивість екрана, а не звіту.
    from app.admin import _listing
    pagination = _certificates_query(filters).paginate(
        page=request.args.get('page', 1, type=int),
        per_page=_listing.per_page_arg(_LIST_PER_PAGE), error_out=False,
    )
    return render_template(
        'admin/certificates.html',
        per_page_options=_listing.PER_PAGE_OPTIONS,
        certificates=pagination.items,
        pagination=pagination,
        stats=_certificate_stats(),
        filters=filters,
        filter_args={k: v for k, v in filters.items() if v},
        state_options=list(_CERT_STATES.items()),
        course_options=[
            (c.id, c.title)
            for c in db.session.query(Course).order_by(Course.title).all()
        ],
        year_options=[(y, str(y)) for y in years],
    )


@admin_bp.route('/certificates/export')
@admin_required
def certificates_export():
    """Експорт реєстру сертифікатів у xlsx з урахуванням активних фільтрів."""
    from app.admin import _listing
    from app.models.course import Course
    from app.services import xlsx_io

    filters = _certificate_filters()
    certs = _certificates_query(filters).all()
    course = (
        db.session.get(Course, filters['course_id'])
        if filters['course_id'] else None
    )
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '--'),
            ('Стан', _CERT_STATES.get(filters['state'], 'Усі')),
            ('Курс', course.title if course else 'Усі'),
            ('Рік видачі', filters['year'] or 'Усі'),
            ('Дата видачі', _listing.date_range_label(filters)),
        ],
        len(certs),
    )
    audit_logger.info(
        'Admin %s exported certificates xlsx (%d rows, filters=%s)',
        current_user.email, len(certs), filters,
    )
    return _listing.xlsx_download(
        xlsx_io.export_certificates_xlsx(certs, applied_filters=summary),
        'certificates',
    )


_USER_ROLES = {'admin': 'Адміністратори', 'user': 'Без адмін-прав'}
_USER_STATES = {'active': 'Активні', 'inactive': 'Неактивні'}
_USER_CONFIRMED = {'yes': 'Email підтверджено', 'no': 'Email не підтверджено'}
_USER_REGS = {'with': 'З реєстраціями', 'without': 'Без реєстрацій'}


def _user_filters():
    """Фільтри списку користувачів -- спільні для сторінки й xlsx-експорту."""
    from app.admin import _listing
    return {
        'q': _listing.text_arg('q'),
        'role': _listing.choice_arg('role', _USER_ROLES),
        'state': _listing.choice_arg('state', _USER_STATES),
        'confirmed': _listing.choice_arg('confirmed', _USER_CONFIRMED),
        'regs': _listing.choice_arg('regs', _USER_REGS),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _users_query(filters):
    """Запит користувачів під фільтри: (rows, reg_count-колонка).

    Кількість реєстрацій -- корельований підзапит (`with_registration_count`),
    тож фільтр «з реєстраціями / без» не тягне окремих SELECT-ів на рядок.
    """
    from sqlalchemy.orm import joinedload
    from app.admin import _listing
    from app.models.medical_profile import MedicalProfile
    from app.models.user import User

    reg_count = User.with_registration_count()
    query = (
        db.session.query(User, reg_count)
        .options(joinedload(User.medical_profile))
        # Пошук ходить і по телефону з анкети, тож профіль джойнимо явно
        # (outer -- користувач без анкети не має зникати зі списку).
        .outerjoin(MedicalProfile, MedicalProfile.user_id == User.id)
    )
    query = _listing.apply_search(query, filters['q'], [
        User.email, User.first_name, User.last_name, MedicalProfile.phone,
    ])
    if filters['role']:
        query = query.filter(User.is_admin.is_(filters['role'] == 'admin'))
    if filters['state']:
        # is_active має NULL у старих рядках -- 'Неактивні' мусить їх ловити.
        if filters['state'] == 'active':
            query = query.filter(User.is_active.is_(True))
        else:
            query = query.filter(db.or_(
                User.is_active.is_(False), User.is_active.is_(None),
            ))
    if filters['confirmed']:
        query = query.filter(User.email_confirmed.is_(filters['confirmed'] == 'yes'))
    if filters['regs']:
        query = query.filter(
            reg_count > 0 if filters['regs'] == 'with' else reg_count == 0
        )
    query = _listing.apply_date_range(
        query, User.created_at, filters['date_from'], filters['date_to'],
    )
    return query.order_by(User.created_at.desc())


def _users_with_counts(rows):
    """(User, count) -> список User із проставленим `_cached_reg_count`.

    Кеш потрібен, щоб шаблон не смикав `registration_count` по одному запиту
    на рядок.
    """
    users = []
    for user, count in rows:
        user._cached_reg_count = count
        users.append(user)
    return users


@admin_bp.route('/users')
@admin_required
def users():
    filters = _user_filters()
    # Базу вже переросли тисячу акаунтів -- сторінками. Експорт лишається по
    # всьому зрізу.
    from app.admin import _listing
    pagination = _users_query(filters).paginate(
        page=request.args.get('page', 1, type=int),
        per_page=_listing.per_page_arg(_LIST_PER_PAGE), error_out=False,
    )
    return render_template(
        'admin/users.html',
        per_page_options=_listing.PER_PAGE_OPTIONS,
        users=_users_with_counts(pagination.items),
        pagination=pagination,
        total_found=pagination.total,
        filters=filters,
        filter_args={k: v for k, v in filters.items() if v},
        role_options=list(_USER_ROLES.items()),
        state_options=list(_USER_STATES.items()),
        confirmed_options=list(_USER_CONFIRMED.items()),
        regs_options=list(_USER_REGS.items()),
    )


@admin_bp.route('/users/export')
@admin_required
def users_export():
    """Експорт користувачів у xlsx з урахуванням активних фільтрів."""
    from app.admin import _listing
    from app.services import xlsx_io

    filters = _user_filters()
    users_list = _users_with_counts(_users_query(filters).all())
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '--'),
            ('Роль', _USER_ROLES.get(filters['role'], 'Усі')),
            ('Стан', _USER_STATES.get(filters['state'], 'Усі')),
            ('Email', _USER_CONFIRMED.get(filters['confirmed'], 'Усі')),
            ('Реєстрації', _USER_REGS.get(filters['regs'], 'Усі')),
            ('Дата реєстрації', _listing.date_range_label(filters)),
        ],
        len(users_list),
    )
    audit_logger.info(
        'Admin %s exported users xlsx (%d rows, filters=%s)',
        current_user.email, len(users_list), filters,
    )
    return _listing.xlsx_download(
        xlsx_io.export_users_xlsx(users_list, applied_filters=summary),
        'users',
    )


@admin_bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def toggle_admin(user_id):
    from app.models.user import User
    user = db.session.get(User, user_id)
    if not user:
        flash('Користувача не знайдено', 'error')
        return redirect(url_for('admin.users'))
    if user.id == current_user.id:
        flash('Неможливо змінити власні повноваження', 'error')
        return redirect(url_for('admin.users'))
    user.is_admin = not user.is_admin
    try:
        db.session.commit()
        status = 'надано' if user.is_admin else 'знято'
        audit_logger.info('Admin %s toggled admin for user %s (%s): %s',
                          current_user.email, user.id, user.email, status)
        flash(f'Адмін-повноваження {status}: {user.email}', 'success')
    except Exception:
        audit_logger.exception('Failed to toggle admin for user %d', user_id)
        db.session.rollback()
        flash('Помилка при оновленні', 'error')
    return redirect(url_for('admin.users'))

# Відгуки: stub замінено повноцінним CRUD -- див. app/admin/routes_reviews.py.


@admin_bp.route('/marketing')
@admin_required
def marketing():
    return render_template('admin/marketing.html')


@admin_bp.route('/integrations/io')
@admin_required
def integrations_io():
    """Сторінка Export/Import конфігурації інтеграцій."""
    return render_template('admin/integration_io.html')


@admin_bp.route('/integrations/export', methods=['POST'])
@admin_required
def integrations_export():
    """Згенерувати .env-блок з SiteSettings і віддати як download."""
    from flask import Response
    from app.models.site_settings import SiteSettings
    from app.services.integration_config_io import export_env

    include_secrets = request.form.get('include_secrets') == 'on'
    try:
        settings = SiteSettings.get()
        text = export_env(settings, include_secrets)
    except Exception:
        logger.exception('integration_config_export failed')
        flash('Помилка при експорті', 'error')
        return redirect(url_for('admin.integrations_io'))

    audit_logger.info(
        'integration_config_exported admin=%s include_secrets=%s',
        current_user.email, include_secrets,
    )
    fname = 'iprm-integrations-secrets.env' if include_secrets else 'iprm-integrations.env'
    return Response(text, mimetype='text/plain', headers={
        'Content-Disposition': f'attachment; filename="{fname}"',
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
    })


@admin_bp.route('/integrations/import-preview', methods=['POST'])
@admin_required
def integrations_import_preview():
    """Parse uploaded .env-text, показати diff без apply."""
    from app.models.site_settings import SiteSettings
    from app.services.integration_config_io import parse_env_text, compute_diff

    text = request.form.get('env_text', '')
    if not text.strip():
        flash('Поле .env порожнє', 'error')
        return redirect(url_for('admin.integrations_io'))

    parsed = parse_env_text(text)
    if not parsed:
        flash('Не вдалося розпарсити .env-блок (або немає відомих ключів)', 'error')
        return redirect(url_for('admin.integrations_io'))

    settings = SiteSettings.get()
    diff = compute_diff(parsed, settings)
    return render_template(
        'admin/integration_import_preview.html',
        diff=diff,
        env_text=text,
        changes_count=sum(1 for d in diff if d['changed']),
    )


@admin_bp.route('/integrations/import-apply', methods=['POST'])
@admin_required
def integrations_import_apply():
    """Apply parsed env values to SiteSettings + commit."""
    from app.models.site_settings import SiteSettings
    from app.services.integration_config_io import parse_env_text, apply_parsed

    text = request.form.get('env_text', '')
    if not text.strip():
        flash('Поле .env порожнє', 'error')
        return redirect(url_for('admin.integrations_io'))

    parsed = parse_env_text(text)
    if not parsed:
        flash('Не вдалося розпарсити .env-блок', 'error')
        return redirect(url_for('admin.integrations_io'))

    settings = SiteSettings.get()
    try:
        n_changes = apply_parsed(parsed, settings)
        db.session.commit()
        audit_logger.info(
            'integration_config_imported admin=%s changes=%d keys=%s',
            current_user.email, n_changes, list(parsed.keys()),
        )
        flash(f'Імпортовано: {n_changes} змін збережено', 'success')
    except Exception:
        db.session.rollback()
        audit_logger.exception('integration_config_import_failed admin=%s', current_user.email)
        flash('Помилка при імпорті', 'error')

    return redirect(url_for('admin.integrations'))


@admin_bp.route('/integrations/health')
@admin_required
def integrations_health():
    """Live health-checks для всіх інтеграцій. ?refresh=1 -- очистити cache.

    Кожен check паралельно робить мінімально-інвазивний live-запит до
    зовнішнього API (Google JWKS, Apple discovery, LiqPay check_status,
    reCAPTCHA siteverify з bogus-токеном). Результати кешуються 60s у
    пам'яті процесу щоб уникнути hammering при rapid-refresh.
    """
    from app.models.site_settings import SiteSettings
    from app.services.integration_health import run_all_checks

    refresh = request.args.get('refresh') == '1'

    try:
        settings = SiteSettings.get()
    except Exception:
        logger.exception('Failed to load SiteSettings for health check')
        flash('Не вдалось завантажити налаштування', 'error')
        return redirect(url_for('admin.integrations'))

    results = run_all_checks(settings, use_cache=not refresh)
    return render_template(
        'admin/integration_health.html',
        results=results,
        refreshed=refresh,
    )


@admin_bp.route('/integrations')
@admin_required
def integrations():
    """Hub-сторінка інтеграцій. Кожен статус збираємо у try/except --
    якщо одна інтеграція збойнула (DB зір'явана, encryption помилка), hub
    усе одно рендериться з 'статус недоступний' бейджем замість 500-ки.
    """
    from app.models.site_settings import SiteSettings
    from app.services.liqpay import get_liqpay_service
    from app.services.recaptcha import get_recaptcha_service

    # Phase Q7: один SiteSettings.get() замість трьох.
    try:
        settings = SiteSettings.get()
    except Exception:
        logger.exception('Failed to load SiteSettings for integrations hub')
        settings = None

    def _safe(getter, default):
        try:
            return getter(), False
        except Exception:
            logger.exception('integrations hub: status getter failed')
            return default, True

    from app.admin._helpers import rotation_status

    if settings is None:
        # Усе недоступне -- але hub все одно показуємо з error-стейтом.
        liqpay_status = {'is_configured': False, 'sandbox': True, 'error': True}
        ga_status = {'is_configured': False, 'error': True}
        meta_pixel_status = {'is_configured': False, 'has_id': False, 'error': True}
        recaptcha_status = {'is_configured': False, 'is_active': False, 'error': True}
        google_oauth_status = {'is_configured': False, 'enabled': False, 'error': True}
        apple_status = {'is_configured': False, 'enabled': False, 'error': True}
    else:
        liqpay_res, liqpay_err = _safe(lambda: get_liqpay_service(settings=settings), None)
        liqpay_status = {
            'is_configured': liqpay_res.is_configured if liqpay_res else False,
            'sandbox': liqpay_res.sandbox if liqpay_res else True,
            'error': liqpay_err,
            'rotation': rotation_status(
                settings.liqpay_private_key_set_at,
                threshold_key='liqpay_private_key',
                is_secret_present=bool(settings.liqpay_private_key),
            ),
        }

        recaptcha_res, recaptcha_err = _safe(lambda: get_recaptcha_service(settings=settings), None)
        recaptcha_status = {
            'is_configured': recaptcha_res.is_configured if recaptcha_res else False,
            'is_active': recaptcha_res.is_active if recaptcha_res else False,
            'error': recaptcha_err,
            'rotation': rotation_status(
                settings.recaptcha_secret_key_set_at,
                threshold_key='recaptcha_secret_key',
                is_secret_present=settings.has_recaptcha_secret_key,
            ),
        }

        ga_id, ga_err = _safe(lambda: settings.effective_google_analytics_id, '')
        ga_status = {'is_configured': bool(ga_id), 'error': ga_err}

        pixel_id, pixel_err = _safe(lambda: settings.effective_meta_pixel_id, '')
        # has_id окремо від is_configured: ID збережений, але прапорець знято --
        # це не "не налаштовано", а свідомо вимкнено, і бейдж має відрізнятись.
        # Обидва читання через _safe: контракт хабу -- збійна інтеграція дає
        # бейдж "статус недоступний", а не 500 на всю сторінку.
        pixel_db_id, pixel_db_err = _safe(lambda: settings.meta_pixel_id, '')
        meta_pixel_status = {
            'is_configured': bool(pixel_id),
            'has_id': bool(pixel_db_id),
            'error': pixel_err or pixel_db_err,
        }

        google_oauth_status = {
            'is_configured': settings.is_google_oauth_configured,
            'enabled': settings.google_oauth_enabled,
            'error': False,
            'rotation': rotation_status(
                settings.google_oauth_client_secret_set_at,
                threshold_key='google_oauth_client_secret',
                is_secret_present=bool(settings.google_oauth_client_secret),
            ),
        }
        apple_status = {
            'is_configured': settings.is_apple_signin_configured,
            'enabled': settings.apple_signin_enabled,
            'error': False,
            'rotation': rotation_status(
                settings.apple_private_key_set_at,
                threshold_key='apple_private_key',
                is_secret_present=bool(settings.apple_private_key),
            ),
        }

    return render_template(
        'admin/integrations.html',
        liqpay_status=liqpay_status,
        ga_status=ga_status,
        meta_pixel_status=meta_pixel_status,
        recaptcha_status=recaptcha_status,
        google_oauth_status=google_oauth_status,
        apple_status=apple_status,
    )
