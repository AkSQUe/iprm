from flask import flash, redirect, render_template, request, url_for, current_app

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin._helpers import save_integration_settings
from app.models.site_settings import SiteSettings


@admin_bp.route('/meta-pixel')
@admin_required
def meta_pixel():
    settings = SiteSettings.get()
    env_id = current_app.config.get('META_PIXEL_ID', '') or ''
    env_enabled = bool(current_app.config.get('META_PIXEL_ENABLED', False))
    effective = settings.effective_meta_pixel_id
    cfg = {
        'db_id': settings.meta_pixel_id or '',
        'db_enabled': bool(settings.meta_pixel_enabled),
        'env_id': env_id,
        'env_enabled': env_enabled,
        'effective_id': effective,
        'is_configured': bool(effective),
        'source': 'db' if settings.meta_pixel_id else ('env' if env_id else 'none'),
    }
    return render_template('admin/meta_pixel.html', cfg=cfg)


@admin_bp.route('/meta-pixel/save', methods=['POST'])
@admin_required
def meta_pixel_save():
    pixel_id = request.form.get('meta_pixel_id', '').strip()
    enabled = request.form.get('meta_pixel_enabled') == 'on'

    if not SiteSettings.is_valid_meta_pixel_id(pixel_id):
        flash('Meta Pixel ID -- 15-16 цифр без пробілів. Скопіюйте саме ID, '
              'а не весь код піксела.', 'error')
        return redirect(url_for('admin.meta_pixel'))

    # Увімкнути без ID неможливо: порожній ID при enabled=True дав би
    # мовчазно неактивну інтеграцію з бейджем "Активно".
    if enabled and not pixel_id and not (
        current_app.config.get('META_PIXEL_ID')
        and current_app.config.get('META_PIXEL_ENABLED')
    ):
        flash('Щоб увімкнути Pixel, спершу вкажіть ID.', 'error')
        return redirect(url_for('admin.meta_pixel'))

    save_integration_settings(
        provider='meta_pixel',
        settings=SiteSettings.get(),
        updates={'meta_pixel_id': pixel_id, 'meta_pixel_enabled': enabled},
        audit_summary={'pixel_id_set': bool(pixel_id), 'enabled': enabled},
        success_msg='Meta Pixel збережено',
    )
    return redirect(url_for('admin.meta_pixel'))


@admin_bp.route('/meta-pixel/test')
@admin_required
def meta_pixel_test():
    """Сторінка перевірки: шле тестову подію у Events Manager.

    Pixel -- client-side, тож "тестувати з'єднання" з сервера, як у reCAPTCHA
    чи LiqPay, неможливо: перевірити треба саме те, що скрипт долітає до
    браузера. Тому окрема сторінка, яка одна на всю адмінку вмикає Pixel
    (services/meta_pixel.py тримає адмінку поза трекінгом) і шле подію.

    Подія нестандартна -- IPRMTestEvent через trackCustom: стандартна назва
    засмітила б звіти конверсій вигаданими Lead/Purchase.
    """
    settings = SiteSettings.get()
    pixel_id = settings.effective_meta_pixel_id
    if not pixel_id:
        flash('Спершу увімкніть Pixel і збережіть ID.', 'error')
        return redirect(url_for('admin.meta_pixel'))
    return render_template('admin/meta_pixel_test.html', pixel_id=pixel_id)
