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
from app.admin._helpers import (
    mask_secret, rotation_status, save_integration_settings,
    validate_recaptcha_secret,
)
from app.extensions import limiter
from app.models.site_settings import SiteSettings
from app.services.recaptcha import get_recaptcha_service

audit_logger = logging.getLogger('audit')


@admin_bp.route('/recaptcha')
@admin_required
def recaptcha():
    # Один SiteSettings.get() замість двох (через get_recaptcha_service +
    # власний виклик).
    settings = SiteSettings.get()
    service = get_recaptcha_service(settings=settings)

    cfg = {
        'enabled': service.enabled,
        'site_key': service.site_key,
        'site_key_masked': mask_secret(service.site_key),
        'secret_key_masked': mask_secret(service.secret_key),
        'score_threshold': service.score_threshold,
        'is_configured': service.is_configured,
        'is_active': service.is_active,
        'source_db_site': bool(settings.recaptcha_site_key),
        'source_db_secret': settings.has_recaptcha_secret_key,
        'rotation': rotation_status(
            settings.recaptcha_secret_key_set_at,
            threshold_key='recaptcha_secret_key',
            is_secret_present=settings.has_recaptcha_secret_key,
        ),
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

    settings = SiteSettings.get()

    # Перевіряємо що буде у БД ПІСЛЯ збереження (порожнє secret-поле
    # зберігає існуюче), щоб правило "enabled вимагає обидва" враховувало
    # вже збережений секрет.
    final_secret = secret_key or settings.recaptcha_secret_key
    if enabled and (not site_key or not final_secret):
        flash(
            'Щоб увімкнути reCAPTCHA, обидва ключі мають бути заповнені',
            'error',
        )
        return redirect(url_for('admin.recaptcha'))

    # Phase A: validate-before-save -- якщо адмін ввів новий secret,
    # перевіряємо через siteverify ДО запису у БД. Якщо невалідний --
    # не зберігаємо, інтеграція не ламається.
    if secret_key:
        ok, msg = validate_recaptcha_secret(secret_key)
        if not ok:
            flash(f'Валідація secret key не пройшла: {msg}', 'error')
            return redirect(url_for('admin.recaptcha'))

    # Guard: порожнє secret-поле НЕ затирає існуючий ключ.
    updates = {
        'recaptcha_site_key': site_key,
        'recaptcha_enabled': enabled,
        'recaptcha_score_threshold': threshold,
    }
    if secret_key:
        updates['recaptcha_secret_key'] = secret_key

    save_integration_settings(
        provider='recaptcha',
        settings=settings,
        updates=updates,
        audit_summary={
            'enabled': enabled,
            'site_key_set': bool(site_key),
            'secret_key_set': bool(secret_key),
            'threshold': threshold,
        },
        success_msg='Налаштування reCAPTCHA збережено',
    )
    return redirect(url_for('admin.recaptcha'))


@admin_bp.route('/recaptcha/test', methods=['POST'])
@admin_required
@limiter.limit("5 per minute")
def recaptcha_test():
    """Перевірка через siteverify з заздалегідь невалідним токеном.
    Google відповідає success=false + error-codes -- значить мережа й secret OK.

    Тест працює навіть коли reCAPTCHA вимкнено (enabled=False) -- щоб
    адмін міг перевірити секрет ПЕРЕД його активацією.
    """
    service = get_recaptcha_service()
    if not service.secret_key:
        flash('Спочатку збережіть Secret Key', 'error')
        return redirect(url_for('admin.recaptcha'))

    # Викликаємо verify напряму, обходячи is_configured-гейт. Бо
    # service.verify() повертає (True, skipped=True) для не-enabled
    # стану, а нам тут потрібна реальна siteverify-перевірка.
    body_encoded = service._build_request_body('___connection_test___', remote_ip='')
    info = service._call_siteverify(body_encoded)
    audit_logger.info('Admin %s tested reCAPTCHA connection', current_user.email)

    if info.get('error') == 'network':
        flash('Не вдалося з\'єднатися з Google API. Перевірте мережу.', 'error')
    elif info.get('error_codes'):
        codes = info['error_codes']
        if 'invalid-input-secret' in codes:
            flash('Secret Key невалідний за форматом', 'error')
        elif 'invalid-input-response' in codes or 'timeout-or-duplicate' in codes:
            flash('З\'єднання з siteverify успішне (тестовий токен очікувано відхилено)', 'success')
        else:
            flash(f'Google повернув помилки: {", ".join(codes)}', 'warning')
    elif info.get('success') is False:
        # Без error_codes, але success=false -- секрет невалідний.
        flash('Secret Key неробочий (Google відхилив без коду помилки)', 'error')
    else:
        flash('Несподівана відповідь від Google API', 'warning')

    return redirect(url_for('admin.recaptcha'))
