"""Admin: Apple Sign In configuration page (Phase 5 of auth unification).

GET  /admin/apple-signin       -- статус, маска ключа, форма
POST /admin/apple-signin/save  -- зберегти team_id/services_id/key_id/private_key
"""
from flask import flash, redirect, render_template, request, url_for

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin._helpers import (
    is_valid_apple_id,
    is_valid_apple_services_id,
    is_valid_apple_private_key,
    mask_secret,
    rotation_status,
    save_integration_settings,
    validate_apple_credentials,
)
from app.models.site_settings import SiteSettings


@admin_bp.route('/apple-signin')
@admin_required
def apple_signin():
    settings = SiteSettings.get()
    cfg = {
        'enabled': settings.apple_signin_enabled,
        'team_id': settings.apple_team_id or '',
        'services_id': settings.apple_services_id or '',
        'key_id': settings.apple_key_id or '',
        'private_key_mask': mask_secret(settings.apple_private_key, style='length'),
        'is_configured': settings.is_apple_signin_configured,
        # Apple вимагає, щоб return URL був зареєстрований у Services ID.
        'redirect_uri': url_for('auth.apple_callback', _external=True),
        'rotation': rotation_status(
            settings.apple_private_key_set_at,
            threshold_key='apple_private_key',
            is_secret_present=bool(settings.apple_private_key),
        ),
    }
    return render_template('admin/apple_signin.html', cfg=cfg)


@admin_bp.route('/apple-signin/save', methods=['POST'])
@admin_required
def apple_signin_save():
    team_id = request.form.get('team_id', '').strip()
    services_id = request.form.get('services_id', '').strip()
    key_id = request.form.get('key_id', '').strip()
    private_key = request.form.get('private_key', '').strip()
    enabled = request.form.get('enabled') == 'on'

    # Backend-валідація (HTML5 pattern працює лише у браузері).
    if not is_valid_apple_id(team_id):
        flash('Team ID має формат 10 uppercase-alphanumeric символів', 'error')
        return redirect(url_for('admin.apple_signin'))
    if not is_valid_apple_id(key_id):
        flash('Key ID має формат 10 uppercase-alphanumeric символів', 'error')
        return redirect(url_for('admin.apple_signin'))
    if not is_valid_apple_services_id(services_id):
        flash('Services ID має формат reverse-DNS (com.example.web)', 'error')
        return redirect(url_for('admin.apple_signin'))
    if private_key and not is_valid_apple_private_key(private_key):
        flash('Private Key має бути PEM-блоком з BEGIN/END PRIVATE KEY маркерами', 'error')
        return redirect(url_for('admin.apple_signin'))

    # Phase A: validate-before-save. Якщо адмін надав НОВИЙ private_key,
    # пробуємо підписати JWT з новими credentials. Якщо JWT не підписався --
    # ключ битий або несумісний з іншими параметрами, не зберігаємо.
    if private_key:
        settings = SiteSettings.get()
        ok, msg = validate_apple_credentials(
            team_id or settings.apple_team_id,
            services_id or settings.apple_services_id,
            key_id or settings.apple_key_id,
            private_key,
        )
        if not ok:
            flash(f'Валідація Apple credentials не пройшла: {msg}', 'error')
            return redirect(url_for('admin.apple_signin'))

    # Порожнє private_key-поле -- не затирає існуючий ключ.
    updates = {
        'apple_team_id': team_id,
        'apple_services_id': services_id,
        'apple_key_id': key_id,
        'apple_signin_enabled': enabled,
    }
    if private_key:
        updates['apple_private_key'] = private_key

    save_integration_settings(
        provider='apple_signin',
        settings=SiteSettings.get(),
        updates=updates,
        audit_summary={
            'enabled': enabled,
            'team_id_set': bool(team_id),
            'services_id_set': bool(services_id),
            'key_id_set': bool(key_id),
            'private_key_set': bool(private_key),
        },
        success_msg='Налаштування Apple Sign In збережено',
    )
    return redirect(url_for('admin.apple_signin'))
