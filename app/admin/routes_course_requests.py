"""Admin: управління запитами на курси (CourseRequest)."""
import logging
from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin._helpers import course_request_counts, try_commit
from app.admin.decorators import admin_required
from app.admin.forms import CourseRequestAdminForm
from app.extensions import db
from app.models.course import Course
from app.models.course_request import CourseRequest, CourseRequestAudit

audit_logger = logging.getLogger('audit')


@admin_bp.route('/course-requests')
@admin_required
def course_requests_list():
    filter_status = request.args.get('status')
    filter_course_id = request.args.get('course_id', type=int)

    query = CourseRequest.query.options(joinedload(CourseRequest.course))
    if filter_status:
        query = query.filter(CourseRequest.status == filter_status)
    if filter_course_id:
        query = query.filter(CourseRequest.course_id == filter_course_id)

    requests_all = query.order_by(CourseRequest.created_at.desc()).all()

    counts = course_request_counts(status='pending')
    if counts:
        courses_by_id = {
            c.id: c for c in Course.query.filter(Course.id.in_(counts.keys())).all()
        }
        counts_by_course = [
            (courses_by_id.get(cid), cnt)
            for cid, cnt in sorted(counts.items(), key=lambda x: -x[1])
        ]
    else:
        counts_by_course = []

    courses = Course.query.order_by(Course.title).all()

    return render_template(
        'admin/course_requests.html',
        requests=requests_all,
        counts_by_course=counts_by_course,
        courses=courses,
        filter_status=filter_status,
        filter_course_id=filter_course_id,
        statuses=CourseRequest.STATUSES,
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
        new_status = form.status.data
        req.status = new_status
        req.admin_notes = form.admin_notes.data
        if new_status != 'pending' and old_status == 'pending':
            req.resolved_by_id = current_user.id
            req.resolved_at = datetime.now(timezone.utc)

        # Audit entry: пишемо при будь-якій зміні статусу (pending->responded,
        # responded->scheduled, scheduled->dismissed тощо). No-op зміни
        # (old == new) не логуємо, щоб не засмічувати історію.
        if old_status != new_status:
            db.session.add(CourseRequestAudit(
                request_id=req.id,
                from_status=old_status,
                to_status=new_status,
                changed_by_id=current_user.id,
                notes=(form.admin_notes.data or '').strip() or None,
            ))

        if try_commit(log_context=f'course_request_edit id={request_id}'):
            audit_logger.info(
                'Admin %s updated request %s status=%s',
                current_user.email, request_id, req.status,
            )
            flash('Запит оновлено', 'success')
            return redirect(url_for('admin.course_requests_list'))

    return render_template('admin/course_request_edit.html', form=form, request_obj=req)


@admin_bp.route('/course-requests/<int:request_id>/delete', methods=['POST'])
@admin_required
def course_request_delete(request_id):
    req = db.session.get(CourseRequest, request_id)
    if not req:
        flash('Запит не знайдено', 'error')
        return redirect(url_for('admin.course_requests_list'))

    db.session.delete(req)
    if try_commit(
        log_context=f'course_request_delete id={request_id}',
        error_msg='Помилка при видаленні',
    ):
        audit_logger.info(
            'Admin %s deleted request %s', current_user.email, request_id,
        )
        flash('Запит видалено', 'success')
    return redirect(url_for('admin.course_requests_list'))
