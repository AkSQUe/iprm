import logging

from flask import flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.site_settings import SiteSettings

audit_logger = logging.getLogger('audit')


@admin_bp.route('/google-analytics')
@admin_required
def google_analytics():
    settings = SiteSettings.get()
    env_fallback = current_app.config.get('GOOGLE_ANALYTICS_ID', '') or ''
    cfg = {
        'db_id': settings.google_analytics_id or '',
        'env_id': env_fallback,
        'effective_id': settings.effective_google_analytics_id,
        'is_configured': bool(settings.effective_google_analytics_id),
        'source': 'db' if settings.google_analytics_id else ('env' if env_fallback else 'none'),
    }
    return render_template('admin/google_analytics.html', cfg=cfg)


@admin_bp.route('/google-analytics/save', methods=['POST'])
@admin_required
def google_analytics_save():
    ga_id = request.form.get('google_analytics_id', '').strip()

    if not SiteSettings.is_valid_ga_id(ga_id):
        flash('GA4 Measurement ID має формат G-XXXXXXXXXX (літери/цифри).', 'error')
        return redirect(url_for('admin.google_analytics'))

    settings = SiteSettings.get()
    settings.google_analytics_id = ga_id
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s updated Google Analytics ID (set=%s)',
            current_user.email,
            bool(ga_id),
        )
        flash('Google Analytics збережено', 'success' if ga_id else 'info')
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to save Google Analytics ID')
        flash('Помилка при збереженні', 'error')

    return redirect(url_for('admin.google_analytics'))
