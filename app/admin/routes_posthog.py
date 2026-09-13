from flask import flash, redirect, render_template, request, session, url_for, current_app

from app.admin import admin_bp
from app.rbac import permission_required
from app.admin._helpers import save_integration_settings, tristate_checkbox
from app.models.site_settings import SiteSettings
from app.services.posthog import posthog_settings_error

# Відхилена форма кладе введене сюди, а сторінка забирає його при наступному
# показі. Без цього після помилки обидва ключі доводилось вводити заново.
FORM_DRAFT_SESSION_KEY = 'posthog_form_draft'


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
        'secondary_recording': settings.effective_posthog_secondary_session_recording,
        'api_host': current_app.config.get('POSTHOG_API_HOST', '/ngx-e'),
        'ui_host': current_app.config.get('POSTHOG_UI_HOST', 'https://eu.posthog.com'),
    }
    # Значення полів форми: чернетка відхиленого збереження або збережений
    # стан. Реплей у додатковий проєкт -- збережена галка, а не діюча: діюча
    # гасне разом з основним рубильником, і показ її в чекбоксі мовчки
    # скидав би вибір при наступному збереженні.
    form = session.pop(FORM_DRAFT_SESSION_KEY, None) or {
        'api_key': cfg['db_key'],
        'secondary_key': cfg['secondary_key'],
        'enabled': cfg['enabled'],
        'recording': cfg['recording'],
        'exclude_admin': cfg['exclude_admin'],
        'secondary_recording': bool(settings.posthog_secondary_session_recording),
    }
    return render_template('admin/posthog.html', cfg=cfg, form=form)


@admin_bp.route('/posthog/save', methods=['POST'])
@permission_required('integrations.keys')
def posthog_save():
    form = {
        'api_key': request.form.get('posthog_project_api_key', '').strip(),
        'secondary_key': request.form.get('posthog_secondary_api_key', '').strip(),
        'enabled': tristate_checkbox('posthog_enabled'),
        'recording': tristate_checkbox('posthog_session_recording'),
        'exclude_admin': tristate_checkbox('posthog_exclude_admin'),
        'secondary_recording': tristate_checkbox('posthog_secondary_session_recording'),
    }

    error = posthog_settings_error(
        api_key=form['api_key'],
        secondary_key=form['secondary_key'],
        enabled=form['enabled'],
        recording=form['recording'],
        secondary_recording=form['secondary_recording'],
        env_key=current_app.config.get('POSTHOG_PROJECT_API_KEY', '') or '',
    )
    if error:
        session[FORM_DRAFT_SESSION_KEY] = form
        flash(error, 'error')
        return redirect(url_for('admin.posthog'))

    save_integration_settings(
        provider='posthog',
        settings=SiteSettings.get(),
        updates={
            'posthog_project_api_key': form['api_key'],
            'posthog_enabled': form['enabled'],
            'posthog_session_recording': form['recording'],
            'posthog_exclude_admin': form['exclude_admin'],
            'posthog_secondary_api_key': form['secondary_key'],
            'posthog_secondary_session_recording': form['secondary_recording'],
        },
        audit_summary={
            'api_key_set': bool(form['api_key']),
            'enabled': form['enabled'],
            'session_recording': form['recording'],
            'exclude_admin': form['exclude_admin'],
            'secondary_api_key_set': bool(form['secondary_key']),
            'secondary_session_recording': form['secondary_recording'],
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
