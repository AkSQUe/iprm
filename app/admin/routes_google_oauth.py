"""Admin: Google OAuth 2.0 configuration page (Phase 3 of auth unification).

GET  /admin/google-oauth         -- статус, маскований secret, форма ключів
POST /admin/google-oauth/save    -- зберегти client_id, secret, enabled
"""
from flask import flash, redirect, render_template, request, url_for

from app.admin import admin_bp
from app.rbac import permission_required
from app.admin._helpers import (
    is_valid_google_client_id,
    mask_secret,
    rotation_status,
    save_integration_settings,
)
from app.models.site_settings import SiteSettings


@admin_bp.route('/google-oauth')
@permission_required('integrations.view')
def google_oauth():
    settings = SiteSettings.get()
    cfg = {
        'enabled': settings.google_oauth_enabled,
        'client_id': settings.google_oauth_client_id or '',
        'client_secret_mask': mask_secret(
            settings.google_oauth_client_secret, style='edges',
        ),
        'is_configured': settings.is_google_oauth_configured,
        # redirect_uri показуємо адміну, щоб він зареєстрував його в GCP
        # OAuth Client -> Authorized redirect URIs.
        'redirect_uri': url_for('auth.google_callback', _external=True),
        'rotation': rotation_status(
            settings.google_oauth_client_secret_set_at,
            threshold_key='google_oauth_client_secret',
            is_secret_present=bool(settings.google_oauth_client_secret),
        ),
    }
    return render_template('admin/google_oauth.html', cfg=cfg)


@admin_bp.route('/google-oauth/save', methods=['POST'])
@permission_required('integrations.keys')
def google_oauth_save():
    client_id = request.form.get('client_id', '').strip()
    client_secret = request.form.get('client_secret', '').strip()
    enabled = request.form.get('enabled') == 'on'

    # Backend-валідація формату client_id (HTML5 pattern працює тільки у браузері).
    if not is_valid_google_client_id(client_id):
        flash(
            'Client ID має формат N-XXX.apps.googleusercontent.com '
            '(скопіюйте з Google Cloud Console)',
            'error',
        )
        return redirect(url_for('admin.google_oauth'))

    settings = SiteSettings.get()
    # Порожнє secret-поле -- не затирає існуючий. Це дозволяє адміну
    # поміняти client_id або enabled-toggle, не вводячи секрет повторно.
    updates = {
        'google_oauth_client_id': client_id,
        'google_oauth_enabled': enabled,
    }
    if client_secret:
        updates['google_oauth_client_secret'] = client_secret

    save_integration_settings(
        provider='google_oauth',
        settings=settings,
        updates=updates,
        audit_summary={
            'enabled': enabled,
            'client_id_set': bool(client_id),
            'secret_set': bool(client_secret),
        },
        success_msg='Налаштування Google OAuth збережено',
    )
    return redirect(url_for('admin.google_oauth'))
