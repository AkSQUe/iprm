"""Admin: Google OAuth 2.0 configuration page (Phase 3 of auth unification).

GET  /admin/google-oauth         -- статус, маскований secret, форма ключів
POST /admin/google-oauth/save    -- зберегти client_id, secret, enabled
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.site_settings import SiteSettings

audit_logger = logging.getLogger('audit')


def _mask(value):
    if not value:
        return ''
    if len(value) <= 8:
        return '****'
    return value[:4] + '****' + value[-4:]


@admin_bp.route('/google-oauth')
@admin_required
def google_oauth():
    settings = SiteSettings.get()
    cfg = {
        'enabled': settings.google_oauth_enabled,
        'client_id': settings.google_oauth_client_id or '',
        'client_secret_mask': _mask(settings.google_oauth_client_secret),
        'is_configured': settings.is_google_oauth_configured,
        # redirect_uri показуємо адміну, щоб він зареєстрував його в GCP
        # OAuth Client -> Authorized redirect URIs.
        'redirect_uri': url_for('auth.google_callback', _external=True),
    }
    return render_template('admin/google_oauth.html', cfg=cfg)


@admin_bp.route('/google-oauth/save', methods=['POST'])
@admin_required
def google_oauth_save():
    client_id = request.form.get('client_id', '').strip()
    client_secret = request.form.get('client_secret', '').strip()
    enabled = request.form.get('enabled') == 'on'

    settings = SiteSettings.get()
    settings.google_oauth_client_id = client_id
    # Не затираємо існуючий secret порожнім полем -- адмін міг зберегти
    # client_id окремо, не вводячи секрет повторно.
    if client_secret:
        settings.google_oauth_client_secret = client_secret
    settings.google_oauth_enabled = enabled

    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s updated Google OAuth config (enabled=%s, client_id_set=%s, secret_set=%s)',
            current_user.email, enabled, bool(client_id), bool(client_secret),
        )
        flash('Налаштування Google OAuth збережено', 'success')
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to save Google OAuth config')
        flash('Помилка при збереженні', 'error')

    return redirect(url_for('admin.google_oauth'))
