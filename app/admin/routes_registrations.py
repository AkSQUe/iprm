from flask import render_template, redirect, url_for, flash, request
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.event import Event
from app.models.registration import EventRegistration


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

    return redirect(url_for('admin.event_registrations', event_id=reg.event_id))


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
    reg.cpd_points_awarded = cpd if cpd is not None else reg.event.cpd_points

    try:
        db.session.commit()
        flash(f'Присутність підтверджено, нараховано {reg.cpd_points_awarded} балів БПР', 'success')
    except Exception:
        db.session.rollback()
        flash('Помилка при оновленні', 'error')

    return redirect(url_for('admin.event_registrations', event_id=reg.event_id))


@admin_bp.route('/registrations')
@admin_required
def registrations_all():
    return render_template(
        'admin/stub.html',
        admin_section='registrations',
        page_title='Реєстрації',
        page_subtitle='Всі реєстрації на заходи',
    )
