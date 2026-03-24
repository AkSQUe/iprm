import logging
from flask import request, redirect, url_for, flash, render_template, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.payments import payments_bp
from app.extensions import db, limiter
from app.models.registration import EventRegistration
from app.services.liqpay import get_liqpay_service

logger = logging.getLogger(__name__)


@payments_bp.route('/liqpay/callback', methods=['POST'])
@limiter.limit('100 per hour;10 per minute')
def liqpay_callback():
    data = request.form.get('data', '')
    signature = request.form.get('signature', '')

    if not data or not signature:
        logger.warning('LiqPay callback: missing data or signature')
        return 'Bad Request', 400

    service = get_liqpay_service()
    ok, message = service.process_callback(data, signature)

    if not ok:
        logger.warning('LiqPay callback failed: %s', message)

    return 'OK', 200


@payments_bp.route('/success')
@login_required
def success():
    order_id = request.args.get('order_id', '')

    if not order_id.startswith('REG-'):
        flash('Невідоме замовлення', 'error')
        return redirect(url_for('main.index'))

    reg_id = int(order_id.split('-', 1)[1])
    reg = db.session.query(EventRegistration).options(
        joinedload(EventRegistration.event),
    ).filter_by(id=reg_id).first()

    if not reg or reg.user_id != current_user.id:
        abort(404)

    if reg.payment_status != 'paid':
        service = get_liqpay_service()
        status_data = service.check_status(order_id)

        if status_data:
            lp_status = status_data.get('status', '')
            payment_id = str(status_data.get('payment_id', ''))

            if lp_status in ('success', 'sandbox'):
                from datetime import datetime, timezone
                reg.payment_status = 'paid'
                reg.payment_id = payment_id
                reg.paid_at = datetime.now(timezone.utc)
                reg.status = 'confirmed'
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

    if reg.payment_status == 'paid':
        return render_template('payments/success.html', reg=reg, event=reg.event)

    flash('Оплата ще обробляється. Оновіть сторінку через хвилину.', 'info')
    return redirect(url_for('registration.confirmation', registration_id=reg.id))


@payments_bp.route('/failure')
@login_required
def failure():
    order_id = request.args.get('order_id', '')
    reg = None

    if order_id.startswith('REG-'):
        reg_id = int(order_id.split('-', 1)[1])
        reg = db.session.query(EventRegistration).options(
            joinedload(EventRegistration.event),
        ).filter_by(id=reg_id).first()
        if reg and reg.user_id != current_user.id:
            reg = None

    return render_template('payments/failure.html', reg=reg)
