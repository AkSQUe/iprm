from flask import flash, redirect, render_template, request, url_for, current_app

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin._helpers import save_integration_settings, tristate_checkbox
from app.models.site_settings import SiteSettings


@admin_bp.route('/google-analytics')
@admin_required
def google_analytics():
    settings = SiteSettings.get()
    env_fallback = current_app.config.get('GOOGLE_ANALYTICS_ID', '') or ''
    cfg = {
        'db_id': settings.google_analytics_id or '',
        'env_id': env_fallback,
        'env_enabled': bool(current_app.config.get('GOOGLE_ANALYTICS_ENABLED', False)),
        'effective_id': settings.effective_google_analytics_id,
        'is_configured': bool(settings.effective_google_analytics_id),
        # Діючий стан прапорця -- саме його показуємо в чекбоксі. Показувати
        # "сире" значення БД означало б знята галка при увімкненому через env
        # трекінгу: інтерфейс суперечив би сам собі.
        'enabled': settings.google_analytics_is_enabled,
        'enabled_source': 'db' if settings.google_analytics_enabled is not None else 'env',
        'source': 'db' if settings.google_analytics_id else ('env' if env_fallback else 'none'),
    }
    return render_template('admin/google_analytics.html', cfg=cfg)


@admin_bp.route('/google-analytics/save', methods=['POST'])
@admin_required
def google_analytics_save():
    ga_id = request.form.get('google_analytics_id', '').strip()
    enabled = tristate_checkbox('google_analytics_enabled')

    if not SiteSettings.is_valid_ga_id(ga_id):
        flash('GA4 Measurement ID має формат G-XXXXXXXXXX (літери/цифри).', 'error')
        return redirect(url_for('admin.google_analytics'))

    # Увімкнути без ID неможливо: інакше вийшла б збережена пустушка --
    # бейдж "Активно" при нулі зібраних даних. Дзеркалить перевірку PostHog.
    env_id = current_app.config.get('GOOGLE_ANALYTICS_ID', '') or ''
    if enabled and not ga_id and not env_id:
        flash('Щоб увімкнути GA, спершу вкажіть Measurement ID.', 'error')
        return redirect(url_for('admin.google_analytics'))

    save_integration_settings(
        provider='google_analytics',
        settings=SiteSettings.get(),
        updates={
            'google_analytics_id': ga_id,
            'google_analytics_enabled': enabled,
        },
        audit_summary={
            'measurement_id_set': bool(ga_id),
            'enabled': enabled,
        },
        success_msg='Google Analytics збережено',
    )
    return redirect(url_for('admin.google_analytics'))
