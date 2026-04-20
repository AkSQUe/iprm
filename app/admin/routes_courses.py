"""Admin CRUD для Course (каталог)."""
import logging

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import CourseForm
from app.extensions import db
from app.models.course import Course
from app.services import course_service, event_service

audit_logger = logging.getLogger('audit')


def _populate_trainer_choices(form):
    from app.models.trainer import Trainer
    trainers = Trainer.query.filter_by(is_active=True).order_by(Trainer.full_name).all()
    form.trainer_id.choices = [(0, '--- Default-тренер не обрано ---')] + [
        (t.id, t.full_name) for t in trainers
    ]


@admin_bp.route('/courses')
@admin_required
def courses_list():
    courses = Course.query.options(
        joinedload(Course.trainer),
    ).order_by(Course.created_at.desc()).all()
    return render_template('admin/courses.html', courses=courses)


@admin_bp.route('/courses/new', methods=['GET', 'POST'])
@admin_required
def course_create():
    form = CourseForm()
    _populate_trainer_choices(form)

    if form.validate_on_submit():
        slug = form.slug.data.strip() or course_service.generate_course_slug(form.title.data)[0]
        if Course.query.filter_by(slug=slug).first():
            flash('Курс з таким slug вже існує', 'error')
            return render_template('admin/course_edit.html', form=form, course=None)

        course = Course(slug=slug, created_by=current_user.id)
        course_service.populate_course_from_form(course, form)
        db.session.add(course)
        db.session.flush()
        course_service.save_program_blocks_for_course(course)

        try:
            db.session.commit()
            audit_logger.info('Admin %s created course %s (%s)', current_user.email, course.id, course.title)
            flash('Курс створено', 'success')
            return redirect(url_for('admin.courses_list'))
        except Exception:
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/course_edit.html', form=form, course=None)


@admin_bp.route('/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@admin_required
def course_edit(course_id):
    course = db.session.get(Course, course_id)
    if not course:
        flash('Курс не знайдено', 'error')
        return redirect(url_for('admin.courses_list'))

    form = CourseForm(obj=course)
    _populate_trainer_choices(form)

    if request.method == 'GET':
        form.target_audience_text.data = event_service.list_to_lines(course.target_audience)
        form.tags_text.data = event_service.list_to_lines(course.tags)
        form.faq_text.data = event_service.faq_list_to_text(course.faq)

    if form.validate_on_submit():
        slug = form.slug.data.strip()
        dup = Course.query.filter(Course.slug == slug, Course.id != course_id).first()
        if dup:
            flash('Курс з таким slug вже існує', 'error')
            return render_template('admin/course_edit.html', form=form, course=course)

        course.slug = slug
        course_service.populate_course_from_form(course, form)
        course_service.save_program_blocks_for_course(course)

        try:
            db.session.commit()
            audit_logger.info('Admin %s updated course %s (%s)', current_user.email, course.id, course.title)
            flash('Курс оновлено', 'success')
            return redirect(url_for('admin.courses_list'))
        except Exception:
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/course_edit.html', form=form, course=course)


@admin_bp.route('/courses/<int:course_id>/delete', methods=['POST'])
@admin_required
def course_delete(course_id):
    course = db.session.get(Course, course_id)
    if course:
        title = course.title
        db.session.delete(course)
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted course %s (%s)', current_user.email, course_id, title)
            flash('Курс видалено', 'success')
        except Exception:
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.courses_list'))
