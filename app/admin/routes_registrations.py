from flask import render_template, redirect, url_for, flash, request
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.event import Event
from app.models.registration import EventRegistration


def _redirect_after_action(reg):
    if request.form.get('next') == 'registrations_all':
        return redirect(url_for('admin.registrations_all'))
    return redirect(url_for('admin.event_registrations', event_id=reg.event_id))


@admin_bp.route('/events/<int:event_id>/registrations')
@admin_required
def event_registrations(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        flash('Захід не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    registrations = EventRegistration.query.options(
        joinedload(EventRegistration.user),
    ).filter_by(event_id=event.id).order_by(
        EventRegistration.created_at.desc()
    ).all()

    return render_template(
        'admin/event_registrations.html',
        event=event,
        registrations=registrations,
    )


@admin_bp.route('/registrations/<int:reg_id>/status', methods=['POST'])
@admin_required
def registration_status(reg_id):
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    new_status = request.form.get('status')
    if new_status in dict(EventRegistration.STATUSES):
        reg.status = new_status
        try:
            db.session.commit()
            flash(f'Статус змінено на "{reg.status_label}"', 'success')
        except Exception:
            db.session.rollback()
            flash('Помилка при оновленні', 'error')

    return _redirect_after_action(reg)


@admin_bp.route('/registrations/<int:reg_id>/attendance', methods=['POST'])
@admin_required
def registration_attendance(reg_id):
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    reg.attended = True
    reg.status = 'completed'
    cpd = request.form.get('cpd_points', type=int)
    max_cpd = (reg.event.cpd_points or 0) * 2
    if cpd is not None and (cpd < 0 or cpd > max(max_cpd, 100)):
        flash('Некоректна кількість балів БПР', 'error')
        return _redirect_after_action(reg)
    reg.cpd_points_awarded = cpd if cpd is not None else reg.event.cpd_points

    try:
        db.session.commit()
        flash(f'Присутність підтверджено, нараховано {reg.cpd_points_awarded} балів БПР', 'success')
    except Exception:
        db.session.rollback()
        flash('Помилка при оновленні', 'error')

    return _redirect_after_action(reg)


@admin_bp.route('/registrations')
@admin_required
def registrations_all():
    status_filter = request.args.get('status', '')
    payment_filter = request.args.get('payment', '')
    event_id_filter = request.args.get('event_id', type=int)

    stats = db.session.query(
        func.count().label('total'),
        func.count(case((EventRegistration.status == 'confirmed', 1))).label('confirmed'),
        func.count(case((EventRegistration.status == 'pending', 1))).label('pending'),
        func.count(case((EventRegistration.status == 'cancelled', 1))).label('cancelled'),
        func.coalesce(
            func.sum(case((EventRegistration.payment_status == 'paid', EventRegistration.payment_amount))),
            0,
        ).label('total_paid'),
    ).one()

    query = EventRegistration.query.options(
        joinedload(EventRegistration.user),
        joinedload(EventRegistration.event),
    )
    if status_filter and status_filter in dict(EventRegistration.STATUSES):
        query = query.filter(EventRegistration.status == status_filter)
    if payment_filter and payment_filter in dict(EventRegistration.PAYMENT_STATUSES):
        query = query.filter(EventRegistration.payment_status == payment_filter)
    if event_id_filter:
        query = query.filter(EventRegistration.event_id == event_id_filter)

    registrations = query.order_by(EventRegistration.created_at.desc()).all()

    events = Event.query.order_by(Event.start_date.desc()).all()

    return render_template(
        'admin/registrations.html',
        registrations=registrations,
        stats=stats,
        events=events,
        filters={
            'status': status_filter,
            'payment': payment_filter,
            'event_id': event_id_filter,
        },
    )
