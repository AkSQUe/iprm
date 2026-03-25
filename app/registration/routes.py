import logging
from flask import render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from app.registration import registration_bp
from app.registration.forms import EventRegistrationForm
from app.extensions import db, limiter
from app.models.event import Event
from app.models.registration import EventRegistration

logger = logging.getLogger(__name__)


@registration_bp.route('/<int:event_id>/register', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per hour", methods=['POST'])
def register(event_id):
    event = db.session.get(Event, event_id)
    if not event or not event.is_active:
        abort(404)

    existing = EventRegistration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first()

    if existing and existing.status != 'cancelled':
        flash('Ви вже зареєстровані на цей захід', 'info')
        return redirect(url_for('registration.confirmation', registration_id=existing.id))

    if not event.is_registration_open:
        flash('Реєстрацію на цей захід закрито', 'error')
        return redirect(url_for('courses.course_by_slug', slug=event.slug))

    form = EventRegistrationForm()

    if form.validate_on_submit():
        is_free = not event.price or event.price == 0

        # Row lock on event to prevent overbooking
        locked_event = db.session.query(Event).with_for_update().filter_by(
            id=event_id
        ).first()
        if locked_event.max_participants:
            active_count = db.session.query(func.count(EventRegistration.id)).filter(
                EventRegistration.event_id == event.id,
                EventRegistration.status.notin_(['cancelled']),
            ).scalar()
            if active_count >= locked_event.max_participants:
                db.session.rollback()
                flash('На жаль, місць більше немає', 'error')
                return redirect(url_for('courses.course_by_slug', slug=event.slug))

        new_status = 'confirmed' if is_free else 'pending'
        new_payment = 'paid' if is_free else 'unpaid'

        if existing and existing.status == 'cancelled':
            # Reuse cancelled row to avoid UniqueConstraint violation
            existing.phone = form.phone.data.strip()
            existing.specialty = form.specialty.data.strip()
            existing.workplace = form.workplace.data.strip()
            existing.experience_years = form.experience_years.data
            existing.license_number = form.license_number.data
            existing.payment_amount = event.price or 0
            existing.status = new_status
            existing.payment_status = new_payment
            existing.payment_id = None
            existing.paid_at = None
            reg = existing
        else:
            reg = EventRegistration(
                user_id=current_user.id,
                event_id=event.id,
                phone=form.phone.data.strip(),
                specialty=form.specialty.data.strip(),
                workplace=form.workplace.data.strip(),
                experience_years=form.experience_years.data,
                license_number=form.license_number.data,
                payment_amount=event.price or 0,
                status=new_status,
                payment_status=new_payment,
            )
            db.session.add(reg)

        try:
            db.session.commit()
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
