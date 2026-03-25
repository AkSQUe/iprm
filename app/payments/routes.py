import logging
from flask import request, redirect, url_for, flash, render_template, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.payments import payments_bp
from app.extensions import db, limiter, csrf
from app.models.registration import EventRegistration
from app.services.liqpay import get_liqpay_service
from app.services.payment_ops import PaymentOps, PERMANENT_ERRORS

logger = logging.getLogger(__name__)


def _parse_order_id(order_id):
    if not order_id.startswith('REG-'):
        raise ValueError('Invalid order format')
    return int(order_id.split('-', 1)[1])


@payments_bp.route('/liqpay/callback', methods=['POST'])
@csrf.exempt
@limiter.limit('100 per hour;10 per minute')
def liqpay_callback():
    data = request.form.get('data', '')
    signature = request.form.get('signature', '')

    if not data or not signature:
        logger.warning('LiqPay callback: missing data or signature')
        return 'Bad Request', 400

    ops = PaymentOps(get_liqpay_service())
    ok, message = ops.process_callback(data, signature)

    if not ok:
        logger.warning('LiqPay callback failed: %s', message)
        status_code = 400 if message in PERMANENT_ERRORS else 500
        return message, status_code

    return 'OK', 200


@payments_bp.route('/success')
@login_required
def success():
    order_id = request.args.get('order_id', '')

    try:
        reg_id = _parse_order_id(order_id)
    except (ValueError, IndexError):
        flash('Невідоме замовлення', 'error')
        return redirect(url_for('main.index'))

    reg = db.session.query(EventRegistration).options(
        joinedload(EventRegistration.event),
    ).filter_by(id=reg_id).first()

    if not reg or reg.user_id != current_user.id:
        abort(404)

    if reg.payment_status != 'paid':
        try:
            ops = PaymentOps(get_liqpay_service())
            ops.check_and_update(reg)
            db.session.refresh(reg)
        except Exception:
            pass

    if reg.payment_status == 'paid':
        return render_template('payments/success.html', reg=reg, event=reg.event)

    flash('Оплата ще обробляється. Оновіть сторінку через хвилину.', 'info')
    return redirect(url_for('registration.confirmation', registration_id=reg.id))


@payments_bp.route('/failure')
@login_required
def failure():
    order_id = request.args.get('order_id', '')
    reg = None

    try:
        reg_id = _parse_order_id(order_id)
        reg = db.session.query(EventRegistration).options(
            joinedload(EventRegistration.event),
        ).filter_by(id=reg_id).first()
        if reg and reg.user_id != current_user.id:
            reg = None
    except (ValueError, IndexError):
        pass

    return render_template('payments/failure.html', reg=reg)
