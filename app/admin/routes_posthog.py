from flask import flash, redirect, render_template, request, url_for, current_app

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin._helpers import save_integration_settings
from app.models.site_settings import SiteSettings


@admin_bp.route('/posthog')
@admin_required
def posthog():
    settings = SiteSettings.get()
    env_key = current_app.config.get('POSTHOG_PROJECT_API_KEY', '') or ''
    env_enabled = bool(current_app.config.get('POSTHOG_ENABLED', False))
    effective = settings.effective_posthog_api_key
    cfg = {
        'db_key': settings.posthog_project_api_key or '',
        'db_enabled': bool(settings.posthog_enabled),
        'db_recording': bool(settings.posthog_session_recording),
        'env_key': env_key,
        'env_enabled': env_enabled,
        'env_recording': bool(current_app.config.get('POSTHOG_SESSION_RECORDING', False)),
        'effective_key': effective,
        'effective_recording': settings.effective_posthog_session_recording,
        'is_configured': bool(effective),
        'source': 'db' if settings.posthog_project_api_key else ('env' if env_key else 'none'),
        'api_host': current_app.config.get('POSTHOG_API_HOST', '/ngx-e'),
        'ui_host': current_app.config.get('POSTHOG_UI_HOST', 'https://eu.posthog.com'),
    }
    return render_template('admin/posthog.html', cfg=cfg)


@admin_bp.route('/posthog/save', methods=['POST'])
@admin_required
def posthog_save():
    api_key = request.form.get('posthog_project_api_key', '').strip()
    enabled = request.form.get('posthog_enabled') == 'on'
    recording = request.form.get('posthog_session_recording') == 'on'

    if not SiteSettings.is_valid_posthog_key(api_key):
        flash('Project API Key починається з "phc_". Ключ, що починається з '
              '"phx_", -- це Personal API Key: він дає доступ до читання '
              'даних проєкту, і в HTML йому не місце.', 'error')
        return redirect(url_for('admin.posthog'))

    # Увімкнути без ключа неможливо: порожній ключ при enabled=True дав би
    # мовчазно неактивну інтеграцію з бейджем "Активно".
    if enabled and not api_key and not (
        current_app.config.get('POSTHOG_PROJECT_API_KEY')
        and current_app.config.get('POSTHOG_ENABLED')
    ):
        flash('Щоб увімкнути PostHog, спершу вкажіть Project API Key.', 'error')
        return redirect(url_for('admin.posthog'))

    # Запис сесій без самої аналітики не має сенсу -- SDK просто не
    # ініціалізується. Мовчки лишити галку увімкненою означало б показувати
    # в адмінці стан, якого насправді немає.
    if recording and not enabled:
        flash('Запис сесій працює лише разом з увімкненим PostHog.', 'error')
        return redirect(url_for('admin.posthog'))

    save_integration_settings(
        provider='posthog',
        settings=SiteSettings.get(),
        updates={
            'posthog_project_api_key': api_key,
            'posthog_enabled': enabled,
            'posthog_session_recording': recording,
        },
        audit_summary={
            'api_key_set': bool(api_key),
            'enabled': enabled,
            'session_recording': recording,
        },
        success_msg='PostHog збережено',
    )
    return redirect(url_for('admin.posthog'))
