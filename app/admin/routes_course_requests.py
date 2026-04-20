"""Admin: управління запитами на курси (CourseRequest)."""
import logging
from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import CourseRequestAdminForm
from app.extensions import db
from app.models.course import Course
from app.models.course_request import CourseRequest

audit_logger = logging.getLogger('audit')


@admin_bp.route('/course-requests')
@admin_required
def course_requests_list():
    filter_status = request.args.get('status')

    query = CourseRequest.query.options(joinedload(CourseRequest.course))
    if filter_status:
        query = query.filter(CourseRequest.status == filter_status)

    requests_all = query.order_by(CourseRequest.created_at.desc()).all()

    # Лічильник по курсах: скільки pending-запитів на кожен
    counts = dict(
        db.session.query(CourseRequest.course_id, func.count(CourseRequest.id))
        .filter(CourseRequest.status == 'pending')
        .group_by(CourseRequest.course_id)
        .all()
    )
    counts_by_course = [
        (Course.query.get(cid), cnt)
        for cid, cnt in sorted(counts.items(), key=lambda x: -x[1])
    ]

    return render_template(
        'admin/course_requests.html',
        requests=requests_all,
        counts_by_course=counts_by_course,
        filter_status=filter_status,
    )


@admin_bp.route('/course-requests/<int:request_id>/edit', methods=['GET', 'POST'])
@admin_required
def course_request_edit(request_id):
    req = db.session.get(CourseRequest, request_id)
    if not req:
        flash('Запит не знайдено', 'error')
        return redirect(url_for('admin.course_requests_list'))

    form = CourseRequestAdminForm(obj=req)

    if form.validate_on_submit():
        old_status = req.status
        req.status = form.status.data
        req.admin_notes = form.admin_notes.data
        if form.status.data != 'pending' and old_status == 'pending':
            req.resolved_by_id = current_user.id
            req.resolved_at = datetime.now(timezone.utc)

        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s updated request %s status=%s',
                current_user.email, request_id, req.status,
            )
            flash('Запит оновлено', 'success')
            return redirect(url_for('admin.course_requests_list'))
        except Exception:
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/course_request_edit.html', form=form, request_obj=req)


@admin_bp.route('/course-requests/<int:request_id>/delete', methods=['POST'])
@admin_required
def course_request_delete(request_id):
    req = db.session.get(CourseRequest, request_id)
    if req:
        db.session.delete(req)
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted request %s', current_user.email, request_id)
            flash('Запит видалено', 'success')
        except Exception:
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.course_requests_list'))
