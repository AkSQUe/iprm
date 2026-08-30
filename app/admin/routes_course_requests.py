"""Admin: управління запитами на курси (CourseRequest)."""
import logging
from datetime import datetime, timezone

from flask import render_template, request, flash
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import _listing, admin_bp
from app.admin._helpers import course_request_counts, try_commit
from app.admin.decorators import admin_required
from app.admin.forms import CourseRequestAdminForm
from app.extensions import db
from app.models.course import Course
from app.models.course_request import CourseRequest, CourseRequestAudit

audit_logger = logging.getLogger('audit')


def _course_request_filters():
    """Фільтри списку запитів на курси -- спільні для сторінки й експорту."""
    return {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', dict(CourseRequest.STATUSES)),
        'course_id': _listing.int_arg('course_id'),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _course_requests_query(filters):
    """Запити під фільтри, найновіші першими."""
    query = CourseRequest.query.options(joinedload(CourseRequest.course))
    query = _listing.apply_search(query, filters['q'], [
        CourseRequest.email, CourseRequest.phone,
        CourseRequest.message, CourseRequest.admin_notes,
    ])
    if filters['status']:
        query = query.filter(CourseRequest.status == filters['status'])
    if filters['course_id']:
        query = query.filter(CourseRequest.course_id == filters['course_id'])
    query = _listing.apply_date_range(
        query, CourseRequest.created_at, filters['date_from'], filters['date_to'],
    )
    return query.order_by(CourseRequest.created_at.desc())


@admin_bp.route('/course-requests')
@admin_required
def course_requests_list():
    filters = _course_request_filters()
    pagination = _course_requests_query(filters).paginate(
        page=request.args.get('page', 1, type=int),
        per_page=_listing.per_page_arg(), error_out=False,
    )

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

    filter_args = _listing.filter_args(filters)
    return render_template(
        'admin/course_requests.html',
        requests=pagination.items,
        pagination=pagination,
        per_page_options=_listing.PER_PAGE_OPTIONS,
        counts_by_course=counts_by_course,
        filters=filters,
        filter_args=filter_args,
        # Форма видалення в рядку веде сюди в action-URL, щоб зберегти й
        # фільтр, і сторінку.
        back_args=_listing.back_args(filter_args, pagination.page),
        status_options=CourseRequest.STATUSES,
        course_options=[
            (c.id, c.title) for c in Course.query.order_by(Course.title).all()
        ],
    )


@admin_bp.route('/course-requests/export')
@admin_required
def course_requests_export():
    """Експорт запитів на курси у xlsx з урахуванням активних фільтрів."""
    from app.services import xlsx_reports

    filters = _course_request_filters()
    rows = _course_requests_query(filters).all()
    course = (
        db.session.get(Course, filters['course_id'])
        if filters['course_id'] else None
    )
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Статус', dict(CourseRequest.STATUSES).get(filters['status'], 'Усі')),
            ('Курс', course.title if course else 'Усі'),
            ('Дата заявки', _listing.date_range_label(filters)),
        ],
        len(rows),
    )
    audit_logger.info(
        'Admin %s exported course requests xlsx (%d rows, filters=%s)',
        current_user.email, len(rows), filters,
    )
    return _listing.xlsx_export(
        rows, 'course-requests',
        lambda: xlsx_reports.export_course_requests_xlsx(rows, applied_filters=summary),
        'admin.course_requests_list', **_listing.filter_args(filters),
    )


@admin_bp.route('/course-requests/<int:request_id>/edit', methods=['GET', 'POST'])
@admin_required
def course_request_edit(request_id):
    req = db.session.get(CourseRequest, request_id)
    if not req:
        flash('Запит не знайдено', 'error')
        return _back()

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
            return _back()

    return render_template('admin/course_request_edit.html', form=form, request_obj=req)


def _back():
    """Безпечний POST -> GET редірект назад до списку зі збереженим зрізом
    (фільтр + СТОРІНКА): без сторінки видалення в рядку на третій сторінці
    щоразу відкидало б менеджера на першу. `_listing.back_redirect`
    перечитує й перевіряє кожен параметр тим самим способом, що й роут
    списку (НЕ request.referrer -- той керований клієнтом і відкриває open
    redirect). Джерело значень -- query-string самого запиту дії: форма
    рядка несе зріз у своєму action-URL через `back_args`.
    """
    return _listing.back_redirect('admin.course_requests_list', _course_request_filters())


@admin_bp.route('/course-requests/<int:request_id>/delete', methods=['POST'])
@admin_required
def course_request_delete(request_id):
    req = db.session.get(CourseRequest, request_id)
    if not req:
        flash('Запит не знайдено', 'error')
        return _back()

    db.session.delete(req)
    if try_commit(
        log_context=f'course_request_delete id={request_id}',
        error_msg='Помилка при видаленні',
    ):
        audit_logger.info(
            'Admin %s deleted request %s', current_user.email, request_id,
        )
        flash('Запит видалено', 'success')
    return _back()
