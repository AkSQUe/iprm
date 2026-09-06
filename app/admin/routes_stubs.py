import logging
from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from app.admin import admin_bp
from app.rbac import permission_required
from app.extensions import db

audit_logger = logging.getLogger('audit')
logger = logging.getLogger(__name__)

@admin_bp.route('/')
@permission_required('dashboard.view')
def dashboard():
    """«/admin» веде на першу сторінку-вхід реєстру, яку користувач має
    право бачити (той самий перелік, що й пункти сайдбару). Раніше редирект
    був на курси, і менеджер без courses.view отримував 403 одразу після
    входу; далі -- фіксований список із шести цілей, і користувач лише з
    materials.view упирався в 403 на логотипі."""
    from app.rbac import registry
    for permission, endpoint in registry.entry_targets():
        if current_user.has_permission(permission):
            return redirect(url_for(endpoint))
    abort(403)


@admin_bp.route('/marketing')
@permission_required('marketing.view')
def marketing():
    return render_template('admin/marketing.html')


@admin_bp.route('/integrations/io')
@permission_required('integrations.keys')
def integrations_io():
    """Сторінка Export/Import конфігурації інтеграцій."""
    return render_template('admin/integration_io.html')


@admin_bp.route('/integrations/export', methods=['POST'])
@permission_required('integrations.keys')
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
@permission_required('integrations.keys')
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
@permission_required('integrations.keys')
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
@permission_required('integrations.view')
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

    # host_url потрібен PostHog-check'у: він мусить пройти власним проксі, а
    # не постукати в апстрім -- у робочому потоці request-контексту немає.
    results = run_all_checks(
        settings, use_cache=not refresh, base_url=request.host_url)
    return render_template(
        'admin/integration_health.html',
        results=results,
        refreshed=refresh,
    )


@admin_bp.route('/integrations')
@permission_required('integrations.view')
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
        posthog_status = {
            'is_configured': False, 'has_key': False,
            'recording': False, 'error': True,
        }
        recaptcha_status = {'is_configured': False, 'is_active': False, 'error': True}
        google_oauth_status = {'is_configured': False, 'enabled': False, 'error': True}
        apple_status = {'is_configured': False, 'enabled': False, 'error': True}
        sintegrum_status = {'is_configured': False, 'enabled': False, 'error': True}
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

        ph_key, ph_err = _safe(lambda: settings.effective_posthog_api_key, '')
        ph_db_key, ph_db_err = _safe(lambda: settings.posthog_project_api_key, '')
        ph_rec, ph_rec_err = _safe(
            lambda: settings.effective_posthog_session_recording, False)
        posthog_status = {
            'is_configured': bool(ph_key),
            'has_key': bool(ph_db_key),
            'recording': bool(ph_rec),
            'error': ph_err or ph_db_err or ph_rec_err,
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
        # Через _safe, як і решта: контракт хабу -- збійна інтеграція дає
        # бейдж "статус недоступний", а не 500 на всю сторінку.
        sintegrum_rotation, sintegrum_err = _safe(
            lambda: rotation_status(
                settings.sintegrum_api_key_set_at,
                soft_days=365, hard_days=730,
                is_secret_present=settings.sintegrum_api_key_is_set,
            ),
            None,
        )
        sintegrum_status = {
            'is_configured': bool(
                settings.sintegrum_api_key_is_set
                and (settings.sintegrum_company_alias or '').strip()
            ),
            'enabled': settings.sintegrum_enabled,
            'error': sintegrum_err,
            'rotation': sintegrum_rotation,
        }

    return render_template(
        'admin/integrations.html',
        liqpay_status=liqpay_status,
        ga_status=ga_status,
        meta_pixel_status=meta_pixel_status,
        posthog_status=posthog_status,
        recaptcha_status=recaptcha_status,
        google_oauth_status=google_oauth_status,
        apple_status=apple_status,
        sintegrum_status=sintegrum_status,
    )
