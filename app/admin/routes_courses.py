"""Admin CRUD для Course (каталог)."""
import logging

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin._helpers import (
    populate_trainer_choices,
    try_commit,
)
from app.admin.decorators import admin_required
from app.admin.forms import CourseForm
from app.extensions import db
from app.models.course import Course
from app.services import course_service

audit_logger = logging.getLogger('audit')


@admin_bp.route('/courses')
@admin_required
def courses_list():
    courses = (
        Course.query.options(joinedload(Course.trainer))
        .order_by(Course.created_at.desc())
        .all()
    )
    # Aggregate upcoming / past / total / pending_requests -- 2 запити замість
    # N+1 через property + немає потреби в selectinload(Course.instances).
    stats = course_service.course_stats([c.id for c in courses])
    empty = {'total': 0, 'upcoming': 0, 'past': 0, 'pending_requests': 0}
    stats_by_id = {c.id: stats.get(c.id, empty) for c in courses}

    return render_template(
        'admin/courses.html',
        courses=courses,
        stats_by_id=stats_by_id,
    )


@admin_bp.route('/courses/new', methods=['GET', 'POST'])
@admin_required
def course_create():
    form = CourseForm()
    populate_trainer_choices(form)

    if form.validate_on_submit():
        slug = form.slug.data.strip() or course_service.generate_course_slug(form.title.data)[0]
        if Course.query.filter_by(slug=slug).first():
            flash('Курс з таким slug вже існує', 'error')
            return render_template('admin/course_edit.html', form=form, course=None)

        course = Course(slug=slug, created_by=current_user.id)
        course_service.populate_course_from_form(course, form)
        db.session.add(course)
        db.session.flush()
        blocks_data = course_service.extract_program_blocks_from_form(request.form)
        course_service.save_program_blocks_for_course(course, blocks_data)

        if try_commit(log_context=f'course_create title={course.title}'):
            audit_logger.info(
                'Admin %s created course %s (%s)',
                current_user.email, course.id, course.title,
            )
            flash('Курс створено', 'success')
            return redirect(url_for('admin.courses_list'))

    return render_template('admin/course_edit.html', form=form, course=None)


@admin_bp.route('/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@admin_required
def course_edit(course_id):
    course = db.session.get(Course, course_id)
    if not course:
        flash('Курс не знайдено', 'error')
        return redirect(url_for('admin.courses_list'))

    form = CourseForm(obj=course)
    populate_trainer_choices(form)

    if request.method == 'GET':
        form.target_audience_text.data = course_service.list_to_lines(course.target_audience)
        form.tags_text.data = course_service.list_to_lines(course.tags)
        form.faq_text.data = course_service.faq_list_to_text(course.faq)

    if form.validate_on_submit():
        slug = form.slug.data.strip()
        dup = Course.query.filter(Course.slug == slug, Course.id != course_id).first()
        if dup:
            flash('Курс з таким slug вже існує', 'error')
            return render_template('admin/course_edit.html', form=form, course=course)

        course.slug = slug
        course_service.populate_course_from_form(course, form)
        blocks_data = course_service.extract_program_blocks_from_form(request.form)
        course_service.save_program_blocks_for_course(course, blocks_data)

        if try_commit(log_context=f'course_edit id={course.id}'):
            audit_logger.info(
                'Admin %s updated course %s (%s)',
                current_user.email, course.id, course.title,
            )
            flash('Курс оновлено', 'success')
            return redirect(url_for('admin.courses_list'))

    return render_template('admin/course_edit.html', form=form, course=course)


@admin_bp.route('/courses/<int:course_id>/clone', methods=['POST'])
@admin_required
def course_clone(course_id):
    source = db.session.get(Course, course_id)
    if not source:
        flash('Курс не знайдено', 'error')
        return redirect(url_for('admin.courses_list'))

    clone = course_service.clone_course(source, created_by_id=current_user.id)
    db.session.flush()

    if try_commit(log_context=f'course_clone source={course_id}'):
        audit_logger.info(
            'Admin %s cloned course %s -> %s',
            current_user.email, source.id, clone.id,
        )
        flash(f'Створено копію "{clone.title}". Відредагуйте назву та активуйте.', 'success')
        return redirect(url_for('admin.course_edit', course_id=clone.id))

    return redirect(url_for('admin.courses_list'))


@admin_bp.route('/courses/<int:course_id>/delete', methods=['POST'])
@admin_required
def course_delete(course_id):
    course = db.session.get(Course, course_id)
    if not course:
        flash('Курс не знайдено', 'error')
        return redirect(url_for('admin.courses_list'))

    title = course.title
    db.session.delete(course)
    if try_commit(
        log_context=f'course_delete id={course_id}',
        error_msg='Помилка при видаленні',
    ):
        audit_logger.info(
            'Admin %s deleted course %s (%s)',
            current_user.email, course_id, title,
        )
        flash('Курс видалено', 'success')
    return redirect(url_for('admin.courses_list'))
