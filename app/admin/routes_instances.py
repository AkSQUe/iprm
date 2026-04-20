"""Admin CRUD для CourseInstance (проведення)."""
import logging

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin._helpers import try_commit, populate_trainer_choices
from app.admin.decorators import admin_required
from app.admin.forms import CourseInstanceForm
from app.extensions import db, limiter
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.services import course_service
from app.services.course_service import InvalidStatusTransition

audit_logger = logging.getLogger('audit')


def _wants_json():
    """Клієнт очікує JSON (AJAX) замість redirect (noscript fallback)."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.accept_mimetypes
    return accept.best_match(['application/json', 'text/html']) == 'application/json'


def _populate_choices(form, preselected_course_id=None):
    courses = (
        Course.query.filter_by(is_active=True)
        .order_by(Course.title)
        .all()
    )
    form.course_id.choices = [(c.id, c.title) for c in courses]
    if preselected_course_id and not form.course_id.data:
        form.course_id.data = preselected_course_id

    populate_trainer_choices(form, empty_label='--- Тренер курсу (default) ---')


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

    # Batch COUNT активних реєстрацій -- інакше шаблон запускає N+1
    # COUNT-ів через inst.registration_count (lazy='dynamic' property).
    if instances:
        reg_counts = dict(
            db.session.query(
                EventRegistration.instance_id,
                func.count(EventRegistration.id),
            )
            .filter(
                EventRegistration.instance_id.in_([i.id for i in instances]),
                EventRegistration.status.notin_(['cancelled']),
            )
            .group_by(EventRegistration.instance_id)
            .all()
        )
    else:
        reg_counts = {}

    courses = (
        Course.query.filter_by(is_active=True)
        .order_by(Course.title)
        .all()
    )
    return render_template(
        'admin/instances.html',
        instances=instances,
        courses=courses,
        reg_counts=reg_counts,
        filter_course_id=filter_course_id,
        filter_status=filter_status,
        statuses=CourseInstance.STATUSES,
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
        if try_commit(log_context=f'instance_create course={form.course_id.data}'):
            audit_logger.info(
                'Admin %s created instance %s (course=%s start=%s)',
                current_user.email, instance.id, instance.course_id, instance.start_date,
            )
            flash('Проведення створено', 'success')
            return redirect(url_for('admin.instances_list'))

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
        if try_commit(log_context=f'instance_edit id={instance.id}'):
            audit_logger.info(
                'Admin %s updated instance %s', current_user.email, instance.id,
            )
            flash('Проведення оновлено', 'success')
            return redirect(url_for('admin.instances_list'))

    return render_template('admin/instance_edit.html', form=form, instance=instance)


@admin_bp.route('/instances/<int:instance_id>/status', methods=['POST'])
@admin_required
@limiter.limit('60 per minute')
def instance_status_update(instance_id):
    wants_json = _wants_json()
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        if wants_json:
            return jsonify({'ok': False, 'error': 'Проведення не знайдено'}), 404
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    new_status = (request.form.get('status') or '').strip()

    try:
        old_status, _ = course_service.change_instance_status(instance, new_status)
    except InvalidStatusTransition as exc:
        if wants_json:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        flash(str(exc), 'error')
        return redirect(url_for('admin.instances_list'))

    if old_status == new_status:
        if wants_json:
            return jsonify({
                'ok': True,
                'status': instance.status,
                'status_label': instance.status_label,
            })
        return redirect(url_for('admin.instances_list'))

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to update instance %s status', instance_id)
        if wants_json:
            return jsonify({'ok': False, 'error': 'Помилка при збереженні'}), 500
        flash('Помилка при збереженні', 'error')
        return redirect(url_for('admin.instances_list'))

    audit_logger.info(
        'Admin %s changed instance %s status: %s -> %s',
        current_user.email, instance_id, old_status, new_status,
    )

    if wants_json:
        return jsonify({
            'ok': True,
            'status': instance.status,
            'status_label': instance.status_label,
        })
    flash(f'Статус змінено на "{instance.status_label}"', 'success')
    return redirect(url_for('admin.instances_list'))


@admin_bp.route('/instances/<int:instance_id>/delete', methods=['POST'])
@admin_required
def instance_delete(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    db.session.delete(instance)
    if try_commit(
        log_context=f'instance_delete id={instance_id}',
        error_msg='Помилка при видаленні',
    ):
        audit_logger.info(
            'Admin %s deleted instance %s', current_user.email, instance_id,
        )
        flash('Проведення видалено', 'success')
    return redirect(url_for('admin.instances_list'))
