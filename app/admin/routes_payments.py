import logging
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.services.liqpay import get_liqpay_service
from app.services.payment_ops import PaymentOps

audit_logger = logging.getLogger('audit')


def _mask_key(key):
    if not key:
        return ''
    if len(key) <= 4:
        return '****'
    return '****' + key[-4:]


@admin_bp.route('/payments')
@admin_required
def payments():
    return redirect(url_for('admin.integrations'))


@admin_bp.route('/liqpay')
@admin_required
def liqpay():
    service = get_liqpay_service()
    cfg = {
        'public_key': _mask_key(service.public_key),
        'private_key': _mask_key(service.private_key),
        'sandbox': service.sandbox,
        'is_configured': service.is_configured,
        'webhook_url': url_for('payments.liqpay_callback', _external=True),
    }

    stats = EventRegistration.payment_stats()

    recent = EventRegistration.query.options(
        joinedload(EventRegistration.instance),
        joinedload(EventRegistration.user),
    ).filter(
        EventRegistration.payment_amount > 0,
    ).order_by(EventRegistration.created_at.desc()).limit(20).all()

    return render_template(
        'admin/liqpay.html',
        cfg=cfg,
        stats=stats,
        recent=recent,
    )


@admin_bp.route('/liqpay/save-keys', methods=['POST'])
@admin_required
def liqpay_save_keys():
    public_key = request.form.get('public_key', '').strip()
    private_key = request.form.get('private_key', '').strip()
    sandbox = request.form.get('sandbox') == 'on'

    if not public_key or not private_key:
        flash('Обидва ключі обов\'язкові', 'error')
        return redirect(url_for('admin.liqpay'))

    settings = SiteSettings.get()
    settings.liqpay_public_key = public_key
    settings.liqpay_private_key = private_key
    settings.liqpay_sandbox = sandbox

    try:
        db.session.commit()
        audit_logger.info('Admin %s updated LiqPay keys (sandbox=%s)', current_user.email, sandbox)
        flash('Ключі LiqPay збережено', 'success')
    except Exception:
        db.session.rollback()
        flash('Помилка при збереженні ключів', 'error')

    return redirect(url_for('admin.liqpay'))


@admin_bp.route('/liqpay/test', methods=['POST'])
@admin_required
def liqpay_test():
    service = get_liqpay_service()
    if not service.is_configured:
        flash('Спочатку збережіть ключі LiqPay', 'error')
        return redirect(url_for('admin.liqpay'))

    result = service.check_status('TEST-0')
    if result is not None:
        lp_err = result.get('err_code', '')
        lp_status = result.get('status', '')
        if lp_err == 'payment_not_found' or lp_status:
            flash('З\'єднання з LiqPay API успішне', 'success')
        else:
            err_desc = result.get('err_description', str(result))
            flash(f'LiqPay API відповів помилкою: {err_desc}', 'error')
    else:
        flash('Не вдалося з\'єднатися з LiqPay API. Перевірте ключі.', 'error')

    audit_logger.info('Admin %s tested LiqPay connection', current_user.email)
    return redirect(url_for('admin.liqpay'))


@admin_bp.route('/liqpay/refund/<int:reg_id>', methods=['POST'])
@admin_required
def liqpay_refund(reg_id):
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.liqpay'))

    ops = PaymentOps(get_liqpay_service())
    ok, msg = ops.initiate_refund(reg, current_user)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('admin.liqpay'))
