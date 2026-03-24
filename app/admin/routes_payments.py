import logging
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy import func as sa_func
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.registration import EventRegistration
from app.services.liqpay import get_liqpay_service
from app.services.payment_ops import PaymentOps
from app.utils import update_env_key

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
    return redirect(url_for('admin.liqpay'))


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

    stats = db.session.query(
        sa_func.count(EventRegistration.id).label('total'),
        sa_func.count(EventRegistration.id).filter(
            EventRegistration.payment_status == 'paid'
        ).label('paid'),
        sa_func.count(EventRegistration.id).filter(
            EventRegistration.payment_status == 'pending'
        ).label('pending'),
        sa_func.count(EventRegistration.id).filter(
            EventRegistration.payment_status == 'refunded'
        ).label('refunded'),
        sa_func.coalesce(sa_func.sum(
            EventRegistration.payment_amount
        ).filter(EventRegistration.payment_status == 'paid'), 0).label('total_amount'),
    ).filter(
        EventRegistration.payment_amount > 0,
    ).one()

    recent = EventRegistration.query.options(
        joinedload(EventRegistration.event),
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
    import os
    from flask import current_app

    public_key = request.form.get('public_key', '').strip()
    private_key = request.form.get('private_key', '').strip()
    sandbox = request.form.get('sandbox') == 'on'

    if not public_key or not private_key:
        flash('Обидва ключі обов\'язкові', 'error')
        return redirect(url_for('admin.liqpay'))

    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    update_env_key(env_path, 'LIQPAY_PUBLIC_KEY', public_key)
    update_env_key(env_path, 'LIQPAY_PRIVATE_KEY', private_key)
    update_env_key(env_path, 'LIQPAY_SANDBOX', 'true' if sandbox else 'false')

    current_app.config['LIQPAY_PUBLIC_KEY'] = public_key
    current_app.config['LIQPAY_PRIVATE_KEY'] = private_key
    current_app.config['LIQPAY_SANDBOX'] = sandbox

    audit_logger.info('Admin %s updated LiqPay keys (sandbox=%s)', current_user.email, sandbox)
    flash('Ключі LiqPay збережено', 'success')
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
