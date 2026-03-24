from flask import render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from app.registration import registration_bp
from app.registration.forms import EventRegistrationForm
from app.extensions import db, limiter
from app.models.event import Event
from app.models.registration import EventRegistration


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

        reg = EventRegistration(
            user_id=current_user.id,
            event_id=event.id,
            phone=form.phone.data.strip(),
            specialty=form.specialty.data.strip(),
            workplace=form.workplace.data.strip(),
            experience_years=form.experience_years.data,
            license_number=form.license_number.data,
            payment_amount=event.price or 0,
            status='confirmed' if is_free else 'pending',
            payment_status='paid' if is_free else 'unpaid',
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
    reg = EventRegistration.query.options(
        joinedload(EventRegistration.event),
    ).get(registration_id)
    if not reg or reg.user_id != current_user.id:
        abort(404)

    return render_template(
        'registration/confirmation.html',
        reg=reg,
        event=reg.event,
    )
