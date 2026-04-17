import logging
from flask import render_template, redirect, url_for, flash, abort, request
from flask_login import login_required, current_user, login_user
from sqlalchemy.orm import joinedload
from app.registration import registration_bp
from app.registration.forms import EventRegistrationForm
from app.extensions import db, limiter
from app.models.event import Event
from app.models.registration import EventRegistration
from app.services import registration_service
from app.services.partner_auth import (
    PrefillTokenError,
    decode_prefill_token,
    get_or_create_partner_user,
)

logger = logging.getLogger(__name__)


def _maybe_consume_prefill_token():
    """If ?prefill=<jwt> is present, auto-login / create user and return payload.

    Returns dict with prefill fields for form rendering, or None.
    On invalid token: logs warning and silently drops prefill (user sees login page).
    """
    token = request.args.get('prefill')
    if not token:
        return None
    try:
        payload = decode_prefill_token(token)
    except PrefillTokenError as exc:
        logger.warning('Prefill token rejected: %s', exc)
        return None

    user = get_or_create_partner_user(payload)
    if not current_user.is_authenticated or current_user.id != user.id:
        login_user(user)
    return {
        'phone': payload.phone or '',
        'first_name': payload.first_name or '',
        'last_name': payload.last_name or '',
    }


@registration_bp.route('/<int:event_id>/register', methods=['GET', 'POST'])
@limiter.limit("10 per hour", methods=['POST'])
def register(event_id):
    prefill = _maybe_consume_prefill_token() if request.method == 'GET' else None

    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=request.full_path))

    if not current_user.email_confirmed:
        flash('Для реєстрації на курс необхідно підтвердити email', 'warning')
        return redirect(url_for('auth.account'))

    event = db.session.get(Event, event_id)
    if not event or not event.is_active:
        abort(404)

    existing = registration_service.find_existing(current_user.id, event.id)

    if existing and existing.status != 'cancelled':
        flash('Ви вже зареєстровані на цей захід', 'info')
        return redirect(url_for('registration.confirmation', registration_id=existing.id))

    if not event.is_registration_open:
        flash('Реєстрацію на цей захід закрито', 'error')
        return redirect(url_for('courses.course_by_slug', slug=event.slug))

    form = EventRegistrationForm(data=prefill) if prefill else EventRegistrationForm()

    if form.validate_on_submit():
        has_capacity, _ = registration_service.check_capacity(event_id)
        if not has_capacity:
            db.session.rollback()
            flash('На жаль, місць більше немає', 'error')
            return redirect(url_for('courses.course_by_slug', slug=event.slug))

        try:
            form_data = {
                'phone': form.phone.data.strip(),
                'specialty': form.specialty.data.strip(),
                'workplace': form.workplace.data.strip(),
                'experience_years': form.experience_years.data,
                'license_number': form.license_number.data,
            }
            reg, is_free = registration_service.create_or_reactivate(
                current_user.id, event, form_data, existing,
            )
            if is_free:
                flash('Реєстрацію підтверджено', 'success')
            else:
                flash('Реєстрацію створено. Очікує оплати.', 'info')
            return redirect(url_for('registration.confirmation', registration_id=reg.id))
        except Exception:
            logger.exception('Failed to register user %d for event %d', current_user.id, event_id)
            db.session.rollback()
            flash('Помилка при реєстрації. Спробуйте ще раз.', 'error')

    return render_template(
        'registration/register.html',
        form=form,
        event=event,
    )


@registration_bp.route('/<int:registration_id>')
@login_required
def confirmation(registration_id):
    reg = db.session.query(EventRegistration).options(
        joinedload(EventRegistration.event),
    ).filter_by(id=registration_id).first()
    if not reg or reg.user_id != current_user.id:
        abort(404)

    liqpay_data = None
    liqpay_signature = None
    liqpay_checkout_url = None

    needs_payment = (
        reg.status == 'pending'
        and reg.payment_status == 'unpaid'
        and reg.payment_amount
        and reg.payment_amount > 0
    )
    if needs_payment:
        from app.services.liqpay import get_liqpay_service
        service = get_liqpay_service()
        if service.is_configured:
            order_id = f'REG-{reg.id}'
            result_url = url_for('payments.success', order_id=order_id, _external=True)
            server_url = url_for('payments.liqpay_callback', _external=True)
            liqpay_data, liqpay_signature, liqpay_checkout_url = (
                service.create_payment_form(
                    order_id=order_id,
                    amount=float(reg.payment_amount),
                    description=reg.event.title,
                    result_url=result_url,
                    server_url=server_url,
                )
            )

    return render_template(
        'registration/confirmation.html',
        reg=reg,
        event=reg.event,
        liqpay_data=liqpay_data,
        liqpay_signature=liqpay_signature,
        liqpay_checkout_url=liqpay_checkout_url,
    )
