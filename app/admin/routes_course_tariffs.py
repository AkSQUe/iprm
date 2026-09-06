"""Admin CRUD шаблонних тарифів курсу (дефолтна вилка, copy-on-create)."""
import logging
from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash
from flask_login import current_user

from app.admin import admin_bp
from app.rbac import permission_required
from app.admin.routes_translations import apply_inline_translations
from app.admin.forms import CourseTariffForm
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_tariff import CourseTariff
from app.services import course_service

audit_logger = logging.getLogger('audit')


@admin_bp.route('/courses/<int:course_id>/tariffs', methods=['GET', 'POST'])
@permission_required('courses.manage')
def course_tariffs(course_id):
    """Список шаблонів вилки курсу + форма додавання."""
    course = db.session.get(Course, course_id)
    if not course:
        flash('Курс не знайдено', 'error')
        return redirect(url_for('admin.courses_list'))

    form = CourseTariffForm()
    if form.validate_on_submit():
        tariff = CourseTariff(
            course_id=course.id,
            name=form.name.data.strip(),
            price=form.price.data,
            description=(form.description.data or '').strip() or None,
            event_format=form.event_format.data or None,
            sort_order=form.sort_order.data if form.sort_order.data is not None else 0,
            is_active=form.is_active.data,
        )
        db.session.add(tariff)
        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s added course tariff "%s" (%s) to course %s',
                current_user.email, tariff.name, tariff.price, course.id,
            )
            flash('Шаблонний тариф додано. Він скопіюється у НОВІ проведення.', 'success')
            return redirect(url_for('admin.course_tariffs', course_id=course.id))
        except Exception:
            db.session.rollback()
            audit_logger.exception('Failed to add course tariff for course %s', course_id)
            flash('Помилка при збереженні', 'error')

    return render_template(
        'admin/course_tariffs.html',
        course=course,
        form=form,
        edit_tariff=None,
    )


@admin_bp.route('/course-tariffs/<int:tariff_id>/edit', methods=['GET', 'POST'])
@permission_required('courses.manage')
def course_tariff_edit(tariff_id):
    tariff = db.session.get(CourseTariff, tariff_id)
    if not tariff:
        flash('Шаблон не знайдено', 'error')
        return redirect(url_for('admin.courses_list'))
    course = tariff.course

    form = CourseTariffForm(obj=tariff)
    if form.validate_on_submit():
        tariff.name = form.name.data.strip()
        tariff.price = form.price.data
        tariff.description = (form.description.data or '').strip() or None
        tariff.event_format = form.event_format.data or None
        tariff.sort_order = form.sort_order.data if form.sort_order.data is not None else 0
        tariff.is_active = form.is_active.data
        apply_inline_translations(tariff)
        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s updated course tariff #%s ("%s") of course %s',
                current_user.email, tariff.id, tariff.name, course.id,
            )
            flash('Шаблон оновлено. Існуючі проведення не змінено.', 'success')
            return redirect(url_for('admin.course_tariffs', course_id=course.id))
        except Exception:
            db.session.rollback()
            audit_logger.exception('Failed to update course tariff #%s', tariff_id)
            flash('Помилка при збереженні', 'error')

    return render_template(
        'admin/course_tariffs.html',
        course=course,
        form=form,
        edit_tariff=tariff,
    )


@admin_bp.route('/course-tariffs/<int:tariff_id>/delete', methods=['POST'])
@permission_required('courses.delete')
def course_tariff_delete(tariff_id):
    tariff = db.session.get(CourseTariff, tariff_id)
    if not tariff:
        flash('Шаблон не знайдено', 'error')
        return redirect(url_for('admin.courses_list'))
    course_id, name = tariff.course_id, tariff.name

    db.session.delete(tariff)
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s deleted course tariff #%s ("%s") of course %s',
            current_user.email, tariff_id, name, course_id,
        )
        flash('Шаблон видалено. Скопійовані тарифи проведень не зачеплено.', 'success')
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to delete course tariff #%s', tariff_id)
        flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.course_tariffs', course_id=course_id))


@admin_bp.route('/courses/<int:course_id>/tariffs/apply', methods=['POST'])
@permission_required('courses.manage')
def course_tariffs_apply(course_id):
    """Застосувати дефолтну вилку до ВСІХ майбутніх проведень курсу.

    Для кожного майбутнього draft/published/active-проведення поточні
    тарифи замінюються шаблонами (тарифи з реєстраціями деактивуються,
    а не видаляються -- історія лишиться).
    """
    course = db.session.get(Course, course_id)
    if not course:
        flash('Курс не знайдено', 'error')
        return redirect(url_for('admin.courses_list'))

    now = datetime.now(timezone.utc)
    instances = (
        CourseInstance.query
        .filter(
            CourseInstance.course_id == course.id,
            CourseInstance.status.in_(('draft', 'published', 'active')),
            db.or_(CourseInstance.start_date.is_(None),
                   CourseInstance.start_date >= now),
        )
        .all()
    )
    total_copied = 0
    try:
        for instance in instances:
            total_copied += course_service.copy_course_tariffs_to_instance(
                instance, replace=True,
            )
        db.session.commit()
        audit_logger.info(
            'Admin %s applied course %s tariffs to %s future instances (%s tariffs)',
            current_user.email, course.id, len(instances), total_copied,
        )
        flash(
            f'Вилку застосовано до {len(instances)} майбутніх проведень '
            f'(скопійовано тарифів: {total_copied})', 'success',
        )
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to apply course %s tariffs', course_id)
        flash('Помилка при застосуванні вилки', 'error')
    return redirect(url_for('admin.course_tariffs', course_id=course.id))


@admin_bp.route('/instances/<int:instance_id>/tariffs/sync', methods=['POST'])
@permission_required('instances.manage')
def instance_tariffs_sync(instance_id):
    """Кнопка "Взяти з курсу": замінити тарифи проведення шаблонами курсу."""
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    try:
        copied = course_service.copy_course_tariffs_to_instance(instance, replace=True)
        db.session.commit()
        audit_logger.info(
            'Admin %s synced tariffs of instance %s from course %s (%s tariffs)',
            current_user.email, instance.id, instance.course_id, copied,
        )
        if copied:
            flash(f'Скопійовано тарифів з курсу: {copied}', 'success')
        else:
            flash('У курсу немає активних шаблонів, що пасують формату проведення', 'warning')
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to sync tariffs for instance %s', instance_id)
        flash('Помилка при копіюванні', 'error')
    return redirect(url_for('admin.instance_tariffs', instance_id=instance.id))
