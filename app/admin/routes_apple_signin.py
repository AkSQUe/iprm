"""Admin: Apple Sign In configuration page (Phase 5 of auth unification).

GET  /admin/apple-signin       -- статус, маска ключа, форма
POST /admin/apple-signin/save  -- зберегти team_id/services_id/key_id/private_key
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.site_settings import SiteSettings

audit_logger = logging.getLogger('audit')


def _mask_key_block(value):
    """Маска для PEM-блоку. Показуємо лише довжину і перші/останні символи
    хедера, щоб адмін бачив що ключ є, без видачі вмісту."""
    if not value:
        return ''
    return f'**** ({len(value)} chars)'


@admin_bp.route('/apple-signin')
@admin_required
def apple_signin():
    settings = SiteSettings.get()
    cfg = {
        'enabled': settings.apple_signin_enabled,
        'team_id': settings.apple_team_id or '',
        'services_id': settings.apple_services_id or '',
        'key_id': settings.apple_key_id or '',
        'private_key_mask': _mask_key_block(settings.apple_private_key),
        'is_configured': settings.is_apple_signin_configured,
        # Apple вимагає, щоб return URL був зареєстрований у Services ID.
        'redirect_uri': url_for('auth.apple_callback', _external=True),
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

    settings = SiteSettings.get()
    settings.apple_team_id = team_id
    settings.apple_services_id = services_id
    settings.apple_key_id = key_id
    # Як і в Google: порожнє поле -- не затирає існуючий ключ.
    if private_key:
        settings.apple_private_key = private_key
    settings.apple_signin_enabled = enabled

    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s updated Apple Sign In (enabled=%s, team_id_set=%s, '
            'services_id_set=%s, key_id_set=%s, private_key_set=%s)',
            current_user.email, enabled,
            bool(team_id), bool(services_id), bool(key_id), bool(private_key),
        )
        flash('Налаштування Apple Sign In збережено', 'success')
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to save Apple Sign In config')
        flash('Помилка при збереженні', 'error')

    return redirect(url_for('admin.apple_signin'))
