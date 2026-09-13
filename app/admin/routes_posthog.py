from flask import flash, redirect, render_template, request, url_for, current_app

from app.admin import admin_bp
from app.rbac import permission_required
from app.admin._helpers import save_integration_settings, tristate_checkbox
from app.models.site_settings import SiteSettings


@admin_bp.route('/posthog')
@permission_required('integrations.view')
def posthog():
    settings = SiteSettings.get()
    env_key = current_app.config.get('POSTHOG_PROJECT_API_KEY', '') or ''
    effective = settings.effective_posthog_api_key
    cfg = {
        'db_key': settings.posthog_project_api_key or '',
        'env_key': env_key,
        'env_enabled': bool(current_app.config.get('POSTHOG_ENABLED', False)),
        'env_recording': bool(current_app.config.get('POSTHOG_SESSION_RECORDING', False)),
        'env_exclude_admin': bool(current_app.config.get('POSTHOG_EXCLUDE_ADMIN', False)),
        'effective_key': effective,
        'is_configured': bool(effective),
        # Діючі стани -- саме їх показуємо в чекбоксах. Показувати "сире"
        # значення БД означало б знята галка при увімкненому через env
        # трекінгу: інтерфейс суперечив би сам собі.
        'enabled': settings.posthog_is_enabled,
        'recording': settings.effective_posthog_session_recording,
        'exclude_admin': settings.effective_posthog_exclude_admin,
        # Звідки прийшло рішення по кожному прапорцю -- 'db' або 'env'.
        'enabled_source': 'db' if settings.posthog_enabled is not None else 'env',
        'recording_source': 'db' if settings.posthog_session_recording is not None else 'env',
        'exclude_admin_source': 'db' if settings.posthog_exclude_admin is not None else 'env',
        'key_source': 'db' if settings.posthog_project_api_key else ('env' if env_key else 'none'),
        'secondary_key': settings.posthog_secondary_api_key or '',
        'effective_secondary_key': settings.effective_posthog_secondary_api_key,
        # Галка форми показує збережене значення, а рядок стану -- діюче:
        # реплей у додатковий проєкт гасне разом з основним рубильником.
        'secondary_recording_saved': bool(settings.posthog_secondary_session_recording),
        'secondary_recording': settings.effective_posthog_secondary_session_recording,
        'api_host': current_app.config.get('POSTHOG_API_HOST', '/ngx-e'),
        'ui_host': current_app.config.get('POSTHOG_UI_HOST', 'https://eu.posthog.com'),
    }
    return render_template('admin/posthog.html', cfg=cfg)


@admin_bp.route('/posthog/save', methods=['POST'])
@permission_required('integrations.keys')
def posthog_save():
    api_key = request.form.get('posthog_project_api_key', '').strip()
    enabled = tristate_checkbox('posthog_enabled')
    recording = tristate_checkbox('posthog_session_recording')
    exclude_admin = tristate_checkbox('posthog_exclude_admin')
    secondary_key = request.form.get('posthog_secondary_api_key', '').strip()
    secondary_recording = 'posthog_secondary_session_recording' in request.form

    if not (SiteSettings.is_valid_posthog_key(api_key)
            and SiteSettings.is_valid_posthog_key(secondary_key)):
        flash('Project API Key починається з "phc_". Ключ, що починається з '
              '"phx_", -- це Personal API Key: він дає доступ до читання '
              'даних проєкту, і в HTML йому не місце.', 'error')
        return redirect(url_for('admin.posthog'))

    # Увімкнути без ключа неможливо: інакше вийшла б збережена пустушка --
    # бейдж "Активно" при нулі зібраних даних.
    env_key = current_app.config.get('POSTHOG_PROJECT_API_KEY', '') or ''
    if enabled and not api_key and not env_key:
        flash('Щоб увімкнути PostHog, спершу вкажіть Project API Key.', 'error')
        return redirect(url_for('admin.posthog'))

    # Той самий ключ двічі -- кожна подія рахувалась би в проєкті вдвічі.
    # Порівнюємо з ключем, який реально діятиме, включно з env.
    if secondary_key and secondary_key == (api_key or env_key):
        flash('Додатковий ключ збігається з основним. Вкажіть ключ іншого '
              'проєкту або залиште поле порожнім.', 'error')
        return redirect(url_for('admin.posthog'))

    if secondary_recording and not secondary_key:
        flash('Запис сесій у додатковий проєкт потребує його ключа.', 'error')
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
            'posthog_exclude_admin': exclude_admin,
            'posthog_secondary_api_key': secondary_key,
            'posthog_secondary_session_recording': secondary_recording,
        },
        audit_summary={
            'api_key_set': bool(api_key),
            'enabled': enabled,
            'session_recording': recording,
            'exclude_admin': exclude_admin,
            'secondary_api_key_set': bool(secondary_key),
            'secondary_session_recording': secondary_recording,
        },
        success_msg='PostHog збережено',
    )
    return redirect(url_for('admin.posthog'))


@admin_bp.route('/posthog/test')
@permission_required('integrations.manage')
def posthog_test():
    """Сторінка перевірки: шле тестову подію і курлить власний проксі.

    Health-check на сторінці інтеграції теж ходить через проксі, але
    з СЕРВЕРА і лише по /static/. Тут перевірка йде з БРАУЗЕРА і тим самим
    шляхом, яким ходять відвідувачі: окремо /ngx-e/static/, окремо
    /ngx-e/array/ і окремо факт того, що SDK справді ініціалізувався.
    Різницю видно, наприклад, коли проксі живий, а CSP ріже blob-воркер.

    Виняток "не трекати адмінку" на цю сторінку не поширюється
    (services/posthog.py::FORCED_ENDPOINTS) -- інакше перевіряти було б
    нічого.
    """
    settings = SiteSettings.get()
    if not settings.effective_posthog_api_key:
        flash('Спершу увімкніть PostHog і збережіть ключ.', 'error')
        return redirect(url_for('admin.posthog'))
    return render_template('admin/posthog_test.html')
