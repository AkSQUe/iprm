from flask import flash, redirect, render_template, request, url_for, current_app

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin._helpers import save_integration_settings
from app.models.site_settings import SiteSettings


def _checkbox(name):
    """Значення тристанного прапорця з форми.

    Форма не вміє надіслати "не задано": знята галка і відсутнє поле
    виглядають однаково. Тому будь-яке збереження робить прапорець ЯВНИМ --
    саме цього ми й хочемо, бо після свідомого тику рішення має належати
    адмінці, а не змінним оточення.
    """
    return request.form.get(name) == 'on'


@admin_bp.route('/posthog')
@admin_required
def posthog():
    settings = SiteSettings.get()
    env_key = current_app.config.get('POSTHOG_PROJECT_API_KEY', '') or ''
    effective = settings.effective_posthog_api_key
    cfg = {
        'db_key': settings.posthog_project_api_key or '',
        'env_key': env_key,
        'env_enabled': bool(current_app.config.get('POSTHOG_ENABLED', False)),
        'env_recording': bool(current_app.config.get('POSTHOG_SESSION_RECORDING', False)),
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
        'api_host': current_app.config.get('POSTHOG_API_HOST', '/ngx-e'),
        'ui_host': current_app.config.get('POSTHOG_UI_HOST', 'https://eu.posthog.com'),
    }
    return render_template('admin/posthog.html', cfg=cfg)


@admin_bp.route('/posthog/save', methods=['POST'])
@admin_required
def posthog_save():
    api_key = request.form.get('posthog_project_api_key', '').strip()
    enabled = _checkbox('posthog_enabled')
    recording = _checkbox('posthog_session_recording')
    exclude_admin = _checkbox('posthog_exclude_admin')

    if not SiteSettings.is_valid_posthog_key(api_key):
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
        },
        audit_summary={
            'api_key_set': bool(api_key),
            'enabled': enabled,
            'session_recording': recording,
            'exclude_admin': exclude_admin,
        },
        success_msg='PostHog збережено',
    )
    return redirect(url_for('admin.posthog'))


@admin_bp.route('/posthog/test')
@admin_required
def posthog_test():
    """Сторінка перевірки: шле тестову подію і курлить власний проксі.

    Потрібна саме окрема сторінка, бо перевірити PostHog з сервера
    неможливо в тій частині, яка найчастіше і ламається. Health-check б'є в
    апстрім PostHog напряму і зламаного проксі не бачить -- а проксі це
    рівно те, що ми тут і будували. Тут же перевірка йде з БРАУЗЕРА і тим
    самим шляхом, яким ходять відвідувачі: /ngx-e/static/, /ngx-e/array/ і
    сам прийом подій.

    Виняток "не трекати адмінку" на цю сторінку не поширюється
    (services/posthog.py::FORCED_ENDPOINTS) -- інакше перевіряти було б
    нічого.
    """
    settings = SiteSettings.get()
    if not settings.effective_posthog_api_key:
        flash('Спершу увімкніть PostHog і збережіть ключ.', 'error')
        return redirect(url_for('admin.posthog'))
    return render_template('admin/posthog_test.html')
