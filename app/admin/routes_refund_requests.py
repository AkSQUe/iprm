"""Admin: черга заявок на повернення коштів.

Черга нічого не повертає -- вона показує, що люди просять, і веде на
сторінку повернення з підставленою сумою. Гроші рухає лише
`/admin/refunds/...`; сюди винесені рішення про заявку, а не про платіж.
"""
import logging

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import _listing, admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.online_enrollment import OnlineEnrollment
from app.models.refund_request import RefundRequest, STATUS_NEW
from app.models.registration import EventRegistration
from app.services import refund_requests

audit_logger = logging.getLogger('audit')


def _filters():
    return {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', dict(RefundRequest.STATUSES)),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
    }


def _query(filters):
    """Заявки під фільтри, найстаріші ВІДКРИТІ першими.

    Порядок саме такий: політика (п. 6.3) дає три робочі дні на відповідь,
    тож зверху має бути та заявка, у якої строк спливає раніше, а не та,
    що надійшла останньою.
    """
    query = RefundRequest.query.options(
        joinedload(RefundRequest.user),
        # До курсу, а не лише до проведення: `RefundRequest.title` читає
        # `instance.course.title`, і без цього кроку кожен рядок черги
        # тягнув би курс окремим запитом.
        joinedload(RefundRequest.registration)
        .joinedload(EventRegistration.instance)
        .joinedload(CourseInstance.course),
        joinedload(RefundRequest.enrollment).joinedload(
            OnlineEnrollment.course),
    )
    query = _listing.apply_search(query, filters['q'], [
        RefundRequest.reason, RefundRequest.decision_note,
    ])
    if filters['status']:
        query = query.filter(RefundRequest.status == filters['status'])
    query = _listing.apply_date_range(
        query, RefundRequest.created_at, filters['date_from'], filters['date_to'],
    )
    return query.order_by(
        (RefundRequest.status != STATUS_NEW),
        RefundRequest.created_at.asc(),
    )


@admin_bp.route('/refund-requests')
@admin_required
def refund_requests_list():
    filters = _filters()
    return render_template(
        'admin/refund_requests.html',
        requests=_query(filters).all(),
        filters=filters,
        filter_args=_listing.filter_args(filters),
        active_status=filters['status'],
        status_options=RefundRequest.STATUSES,
        new_count=refund_requests.pending_count(),
    )


@admin_bp.route('/refund-requests/export')
@admin_required
def refund_requests_export():
    """Вивантажити поточний зріз заявок у xlsx."""
    from app.services import xlsx_reports

    filters = _filters()
    rows = _query(filters).all()
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Статус', dict(RefundRequest.STATUSES).get(filters['status'], 'Усі')),
            ('Дата подання', _listing.date_range_label(filters)),
        ],
        len(rows),
    )
    audit_logger.info(
        'Admin %s exported refund requests xlsx (%d rows, filters=%s)',
        current_user.email, len(rows), filters,
    )
    return _listing.xlsx_export(
        rows, 'refund-requests',
        lambda: xlsx_reports.export_refund_requests_xlsx(
            rows, applied_filters=summary),
        'admin.refund_requests_list', **_listing.filter_args(filters),
    )


@admin_bp.route('/refund-requests/<int:request_id>/reject', methods=['POST'])
@admin_required
def refund_request_reject(request_id):
    item = db.session.get(RefundRequest, request_id)
    if item is None:
        flash('Заявку не знайдено', 'error')
        return redirect(url_for('admin.refund_requests_list'))

    note = (request.form.get('decision_note') or '').strip()
    if not note:
        # Відмова без пояснення -- це та сама тиша, від якої заявка й мала
        # рятувати: людина не дізнається, що робити далі.
        flash('Вкажіть причину відмови: вона піде в лист учаснику', 'error')
        return redirect(url_for('admin.refund_requests_list'))

    ok, message = refund_requests.reject(item, current_user, note)
    flash(message, 'success' if ok else 'error')
    return redirect(url_for(
        'admin.refund_requests_list',
        **{k: v for k, v in _filters().items() if v},
    ))
