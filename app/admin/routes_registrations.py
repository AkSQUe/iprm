import logging
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


def _redirect_after_action(reg):
    if request.form.get('next') == 'registrations_all':
        return redirect(url_for('admin.registrations_all'))
    if reg.instance_id:
        return redirect(url_for('admin.instance_registrations', instance_id=reg.instance_id))
    return redirect(url_for('admin.registrations_all'))


@admin_bp.route('/instances/<int:instance_id>/registrations')
@admin_required
def instance_registrations(instance_id):
    instance = db.session.query(CourseInstance).options(
        joinedload(CourseInstance.course),
    ).filter_by(id=instance_id).first()
    if not instance:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    registrations = EventRegistration.query.options(
        joinedload(EventRegistration.user),
    ).filter_by(instance_id=instance.id).order_by(
        EventRegistration.created_at.desc()
    ).all()

    return render_template(
        'admin/instance_registrations.html',
        instance=instance,
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
        old_status = reg.status
        reg.status = new_status
        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s changed reg %d status: %s -> %s',
                current_user.email, reg_id, old_status, new_status,
            )
            flash(f'Статус змінено на "{reg.status_label}"', 'success')

            try:
                from app.services.email_service import EmailService
                EmailService.send_status_change(reg, old_status, new_status)
            except Exception:
                logger.exception('Failed to queue status change email for reg %d', reg_id)

        except Exception:
            logger.exception('Failed to update registration %d status', reg_id)
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
    # max cap = 2x the instance's effective cpd (або принаймні 100)
    base_cpd = reg.instance.effective_cpd_points if reg.instance else 0
    max_cpd = (base_cpd or 0) * 2
    if cpd is not None and (cpd < 0 or cpd > max(max_cpd, 100)):
        flash('Некоректна кількість балів БПР', 'error')
        return _redirect_after_action(reg)
    reg.cpd_points_awarded = cpd if cpd is not None else base_cpd

    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s confirmed attendance reg %d, CPD=%s',
            current_user.email, reg_id, reg.cpd_points_awarded,
        )
        flash(f'Присутність підтверджено, нараховано {reg.cpd_points_awarded} балів БПР', 'success')
    except Exception:
        logger.exception('Failed to update attendance for registration %d', reg_id)
        db.session.rollback()
        flash('Помилка при оновленні', 'error')

    return _redirect_after_action(reg)


@admin_bp.route('/registrations')
@admin_required
def registrations_all():
    status_filter = request.args.get('status', '')
    payment_filter = request.args.get('payment', '')
    instance_id_filter = request.args.get('instance_id', type=int)

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
        joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
    )
    if status_filter and status_filter in dict(EventRegistration.STATUSES):
        query = query.filter(EventRegistration.status == status_filter)
    if payment_filter and payment_filter in dict(EventRegistration.PAYMENT_STATUSES):
        query = query.filter(EventRegistration.payment_status == payment_filter)
    if instance_id_filter:
        query = query.filter(EventRegistration.instance_id == instance_id_filter)

    registrations = query.order_by(EventRegistration.created_at.desc()).all()

    instances = db.session.query(CourseInstance).options(
        joinedload(CourseInstance.course),
    ).order_by(CourseInstance.start_date.desc()).all()

    return render_template(
        'admin/registrations.html',
        registrations=registrations,
        stats=stats,
        instances=instances,
        filters={
            'status': status_filter,
            'payment': payment_filter,
            'instance_id': instance_id_filter,
        },
    )
