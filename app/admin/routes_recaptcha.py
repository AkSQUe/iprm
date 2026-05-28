"""Admin: reCAPTCHA v3 configuration page.

GET  /admin/recaptcha             -- статус, маскований secret, форма ключів
POST /admin/recaptcha/save-keys   -- зберегти ключі/поріг/enabled у SiteSettings
POST /admin/recaptcha/test        -- перевірка з'єднання з siteverify
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.site_settings import SiteSettings
from app.services.recaptcha import get_recaptcha_service

audit_logger = logging.getLogger('audit')


def _mask_key(key):
    if not key:
        return ''
    if len(key) <= 4:
        return '****'
    return '****' + key[-4:]


@admin_bp.route('/recaptcha')
@admin_required
def recaptcha():
    service = get_recaptcha_service()
    settings = SiteSettings.get()

    cfg = {
        'enabled': service.enabled,
        'site_key': service.site_key,
        'site_key_masked': _mask_key(service.site_key),
        'secret_key_masked': _mask_key(service.secret_key),
        'score_threshold': service.score_threshold,
        'is_configured': service.is_configured,
        'is_active': service.is_active,
        'source_db_site': bool(settings.recaptcha_site_key),
        'source_db_secret': bool(settings._recaptcha_secret_key_encrypted),
    }
    return render_template('admin/recaptcha.html', cfg=cfg)


@admin_bp.route('/recaptcha/save-keys', methods=['POST'])
@admin_required
def recaptcha_save_keys():
    site_key = request.form.get('site_key', '').strip()
    secret_key = request.form.get('secret_key', '').strip()
    enabled = request.form.get('enabled') == 'on'

    try:
        threshold = float(request.form.get('score_threshold', '0.5'))
    except (TypeError, ValueError):
        flash('Поріг score має бути числом 0..1', 'error')
        return redirect(url_for('admin.recaptcha'))

    if threshold < 0.0 or threshold > 1.0:
        flash('Поріг score має бути в межах 0.0..1.0', 'error')
        return redirect(url_for('admin.recaptcha'))

    if enabled and (not site_key or not secret_key):
        flash(
            'Щоб увімкнути reCAPTCHA, обидва ключі мають бути заповнені',
            'error',
        )
        return redirect(url_for('admin.recaptcha'))

    settings = SiteSettings.get()
    settings.recaptcha_site_key = site_key
    # setter сам зашифрує (або очистить при пустому value)
    settings.recaptcha_secret_key = secret_key
    settings.recaptcha_enabled = enabled
    settings.recaptcha_score_threshold = threshold

    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s updated reCAPTCHA settings (enabled=%s, threshold=%.2f)',
            current_user.email, enabled, threshold,
        )
        flash('Налаштування reCAPTCHA збережено', 'success')
    except Exception:
        db.session.rollback()
        flash('Помилка при збереженні налаштувань', 'error')

    return redirect(url_for('admin.recaptcha'))


@admin_bp.route('/recaptcha/test', methods=['POST'])
@admin_required
def recaptcha_test():
    """Перевірка через siteverify з заздалегідь невалідним токеном.
    Google відповідає success=false + error-codes -- значить мережа й secret OK.
    """
    service = get_recaptcha_service()
    if not service.secret_key:
        flash('Спочатку збережіть Secret Key', 'error')
        return redirect(url_for('admin.recaptcha'))

    ok, info = service.verify('___connection_test___', expected_action=None)
    audit_logger.info('Admin %s tested reCAPTCHA connection', current_user.email)

    if info.get('skipped'):
        if info.get('error') == 'network':
            flash('Не вдалося з\'єднатися з Google API. Перевірте мережу.', 'error')
        else:
            flash('reCAPTCHA не сконфігурована (увімкніть і збережіть ключі)', 'warning')
    elif info.get('error_codes'):
        codes = info['error_codes']
        if 'invalid-input-secret' in codes:
            flash('Secret Key невалідний за форматом', 'error')
        elif 'invalid-input-response' in codes or 'timeout-or-duplicate' in codes:
            flash('З\'єднання з siteverify успішне (тестовий токен очікувано відхилено)', 'success')
        else:
            flash(f'Google повернув помилки: {", ".join(codes)}', 'warning')
    else:
        flash('Несподівана відповідь від Google API', 'warning')

    return redirect(url_for('admin.recaptcha'))
