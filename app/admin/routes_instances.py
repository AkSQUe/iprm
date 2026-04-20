"""Admin CRUD для CourseInstance (проведення)."""
import logging

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import CourseInstanceForm
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.services import course_service

audit_logger = logging.getLogger('audit')


def _populate_choices(form, preselected_course_id=None):
    from app.models.trainer import Trainer
    courses = Course.query.filter_by(is_active=True).order_by(Course.title).all()
    form.course_id.choices = [(c.id, c.title) for c in courses]
    if preselected_course_id and not form.course_id.data:
        form.course_id.data = preselected_course_id

    trainers = Trainer.query.filter_by(is_active=True).order_by(Trainer.full_name).all()
    form.trainer_id.choices = [(0, '--- Тренер курсу (default) ---')] + [
        (t.id, t.full_name) for t in trainers
    ]


@admin_bp.route('/instances')
@admin_required
def instances_list():
    filter_course_id = request.args.get('course_id', type=int)
    filter_status = request.args.get('status')

    query = CourseInstance.query.options(
        joinedload(CourseInstance.course),
        joinedload(CourseInstance.trainer),
    )
    if filter_course_id:
        query = query.filter(CourseInstance.course_id == filter_course_id)
    if filter_status:
        query = query.filter(CourseInstance.status == filter_status)

    instances = query.order_by(CourseInstance.start_date.desc()).all()
    courses = Course.query.order_by(Course.title).all()
    return render_template(
        'admin/instances.html',
        instances=instances,
        courses=courses,
        filter_course_id=filter_course_id,
        filter_status=filter_status,
    )


@admin_bp.route('/instances/new', methods=['GET', 'POST'])
@admin_required
def instance_create():
    preselected = request.args.get('course_id', type=int)
    form = CourseInstanceForm()
    _populate_choices(form, preselected)

    if form.validate_on_submit():
        instance = CourseInstance()
        course_service.populate_instance_from_form(instance, form)
        db.session.add(instance)
        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s created instance %s (course=%s start=%s)',
                current_user.email, instance.id, instance.course_id, instance.start_date,
            )
            flash('Проведення створено', 'success')
            return redirect(url_for('admin.instances_list'))
        except Exception:
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/instance_edit.html', form=form, instance=None)


@admin_bp.route('/instances/<int:instance_id>/edit', methods=['GET', 'POST'])
@admin_required
def instance_edit(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    form = CourseInstanceForm(obj=instance)
    _populate_choices(form)

    if form.validate_on_submit():
        course_service.populate_instance_from_form(instance, form)
        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s updated instance %s', current_user.email, instance.id,
            )
            flash('Проведення оновлено', 'success')
            return redirect(url_for('admin.instances_list'))
        except Exception:
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/instance_edit.html', form=form, instance=instance)


@admin_bp.route('/instances/<int:instance_id>/status', methods=['POST'])
@admin_required
def instance_status_update(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        return jsonify({'ok': False, 'error': 'Проведення не знайдено'}), 404

    new_status = (request.form.get('status') or '').strip()
    if new_status not in dict(CourseInstance.STATUSES):
        return jsonify({'ok': False, 'error': 'Невідомий статус'}), 400

    instance.status = new_status
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s changed instance %s status -> %s',
            current_user.email, instance_id, new_status,
        )
        return jsonify({'ok': True, 'status': instance.status, 'status_label': instance.status_label})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'Помилка при збереженні'}), 500


@admin_bp.route('/instances/<int:instance_id>/delete', methods=['POST'])
@admin_required
def instance_delete(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if instance:
        db.session.delete(instance)
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted instance %s', current_user.email, instance_id)
            flash('Проведення видалено', 'success')
        except Exception:
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.instances_list'))
