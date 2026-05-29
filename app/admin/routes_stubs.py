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


@admin_bp.route('/certificates')
@admin_required
def certificates():
    return render_template(
        'admin/stub.html',
        admin_section='certificates',
        page_title='Сертифікати',
        page_subtitle='Управління сертифікатами слухачів',
    )


@admin_bp.route('/users')
@admin_required
def users():
    from app.models.user import User
    reg_count = User.with_registration_count()
    rows = db.session.query(User, reg_count).order_by(User.created_at.desc()).all()

    all_users = []
    for user, count in rows:
        user._cached_reg_count = count
        all_users.append(user)

    return render_template('admin/users.html', users=all_users)


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


@admin_bp.route('/reviews')
@admin_required
def reviews():
    return render_template(
        'admin/stub.html',
        admin_section='reviews',
        page_title='Відгуки',
        page_subtitle='Відгуки учасників на заходи',
    )


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
        recaptcha_status=recaptcha_status,
        google_oauth_status=google_oauth_status,
        apple_status=apple_status,
    )
