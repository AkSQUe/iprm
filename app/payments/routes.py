import logging
from flask import request, redirect, url_for, flash, render_template, abort
from flask_babel import gettext as _
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.payments import payments_bp
from app.extensions import db, limiter, csrf
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.services.liqpay import get_liqpay_service
from app.services.payment_ops import PaymentOps, PERMANENT_ERRORS

logger = logging.getLogger(__name__)


def _parse_order_id(order_id):
    """Числовий id реєстрації з REG-<id>. Онлайн-курси мають свій розбір."""
    if not order_id.startswith('REG-'):
        raise ValueError('Invalid order format')
    return int(order_id.split('-', 1)[1])


def _enrollment_from_order(order_id):
    """Замовлення онлайн-курсу поточного користувача або None."""
    from app.models.online_enrollment import OnlineEnrollment
    from app.services.payment_ops import parse_order_id

    kind, enrollment_id = parse_order_id(order_id)
    if kind != 'enrollment' or enrollment_id is None:
        return None
    enrollment = db.session.get(OnlineEnrollment, enrollment_id)
    if not enrollment or enrollment.user_id != current_user.id:
        return None
    return enrollment


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
@limiter.limit('5 per minute')
def success():
    order_id = request.args.get('order_id', '')

    if order_id.startswith('ONL-'):
        return _online_success(order_id)

    try:
        reg_id = _parse_order_id(order_id)
    except (ValueError, IndexError):
        flash(_('Невідоме замовлення'), 'error')
        return redirect(url_for('main.index'))

    reg = db.session.query(EventRegistration).options(
        # course -- база для підбору рекомендацій нижче на сторінці.
        joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
    ).filter_by(id=reg_id).first()

    if not reg or reg.user_id != current_user.id:
        abort(404)

    if reg.payment_status != 'paid':
        try:
            ops = PaymentOps(get_liqpay_service())
            ops.check_and_update(reg)
            db.session.refresh(reg)
        except Exception:
            logger.exception('Failed to poll LiqPay for REG-%d on success page', reg_id)

    if reg.payment_status == 'paid':
        # Крос-сел: щойно оплачений курс (і решта вже куплених) виключається
        # всередині сервісу за реєстраціями користувача.
        from app.services.course_recommend import recommend_context
        base = reg.instance.course if reg.instance else None
        return render_template(
            'payments/success.html', reg=reg, event=reg.instance,
            **recommend_context(base_course=base, user=current_user),
        )

    flash(_('Оплата ще обробляється. Оновіть сторінку через хвилину.'), 'info')
    return redirect(url_for('registration.confirmation', registration_id=reg.id))


def _online_success(order_id):
    """Сторінка «оплату отримано» для онлайн-курсу.

    Як і для заходів, тут можлива гонка з callback-ом: користувач
    повертається з LiqPay швидше, ніж приходить серверне сповіщення.
    Тому статус за потреби перепитуємо синхронно.
    """
    enrollment = _enrollment_from_order(order_id)
    if enrollment is None:
        flash(_('Невідоме замовлення'), 'error')
        return redirect(url_for('main.index'))

    if enrollment.payment_status != 'paid':
        try:
            ops = PaymentOps(get_liqpay_service())
            ops.check_enrollment_and_update(enrollment)
            db.session.refresh(enrollment)
        except Exception:
            logger.exception('Failed to poll LiqPay for %s on success page', order_id)

    if enrollment.payment_status == 'paid':
        return render_template('online/success.html', enrollment=enrollment,
                               course=enrollment.course)

    flash(_('Оплата ще обробляється. Оновіть сторінку через хвилину.'), 'info')
    return redirect(url_for('online.course_detail', slug=enrollment.course.slug))


@payments_bp.route('/failure')
@login_required
def failure():
    order_id = request.args.get('order_id', '')
    reg = None

    if order_id.startswith('ONL-'):
        enrollment = _enrollment_from_order(order_id)
        return render_template('online/failure.html', enrollment=enrollment,
                               course=enrollment.course if enrollment else None)

    try:
        reg_id = _parse_order_id(order_id)
        reg = db.session.query(EventRegistration).options(
            joinedload(EventRegistration.instance),
        ).filter_by(id=reg_id).first()
        if reg and reg.user_id != current_user.id:
            reg = None
    except (ValueError, IndexError):
        pass

    return render_template('payments/failure.html', reg=reg)
