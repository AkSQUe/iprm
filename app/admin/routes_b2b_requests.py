"""Admin: заявки на корпоративне навчання (B2B, блок "Для команд і клінік")."""
import logging

from flask import render_template, flash, request
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.b2b_request import B2BRequest

audit_logger = logging.getLogger('audit')


def _b2b_filters():
    """Фільтри списку B2B-заявок -- спільні для сторінки й експорту."""
    return {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', dict(B2BRequest.STATUSES)),
        'team_size': _listing.choice_arg('team_size', dict(B2BRequest.TEAM_SIZES)),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _b2b_query(filters):
    """Заявки під фільтри, найновіші першими."""
    query = _listing.apply_search(B2BRequest.query, filters['q'], [
        B2BRequest.first_name, B2BRequest.last_name,
        B2BRequest.email, B2BRequest.phone, B2BRequest.admin_notes,
    ])
    if filters['status']:
        query = query.filter(B2BRequest.status == filters['status'])
    if filters['team_size']:
        query = query.filter(B2BRequest.team_size == filters['team_size'])
    query = _listing.apply_date_range(
        query, B2BRequest.created_at, filters['date_from'], filters['date_to'],
    )
    return query.order_by(B2BRequest.created_at.desc())


@admin_bp.route('/b2b-requests')
@admin_required
def b2b_requests_list():
    filters = _b2b_filters()
    pagination = _b2b_query(filters).paginate(
        page=_listing.page_arg(),
        per_page=_listing.per_page_arg(), error_out=False,
    )
    filter_args = _listing.filter_args(filters)
    return render_template(
        'admin/b2b_requests.html',
        requests=pagination.items,
        pagination=pagination,
        per_page_options=_listing.PER_PAGE_OPTIONS,
        filters=filters,
        filter_args=filter_args,
        # Дія з рядка (форма статусу) веде сюди в action-URL, щоб зберегти
        # і фільтр, і сторінку -- інакше збереження скидає на першу сторінку.
        back_args=_listing.back_args(filter_args, pagination.page),
        active_status=filters['status'],
        status_options=B2BRequest.STATUSES,
        team_size_options=B2BRequest.TEAM_SIZES,
        new_count=B2BRequest.query.filter_by(status='new').count(),
    )


@admin_bp.route('/b2b-requests/export')
@admin_required
def b2b_requests_export():
    """Експорт B2B-заявок у xlsx з урахуванням активних фільтрів."""
    from app.services import xlsx_reports

    filters = _b2b_filters()
    # Стелю рядків міряємо COUNT-ом ДО вибірки: інакше зріз спершу
    # піднімався б у пам'ять цілком і лише потім отримував відмову.
    rows, refusal = _listing.export_query(
        _b2b_query(filters), 'admin.b2b_requests_list', **_listing.filter_args(filters),
    )
    if refusal:
        return refusal
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Статус', dict(B2BRequest.STATUSES).get(filters['status'], 'Усі')),
            ('Розмір команди',
             dict(B2BRequest.TEAM_SIZES).get(filters['team_size'], 'Усі')),
            ('Дата заявки', _listing.date_range_label(filters)),
        ],
        len(rows),
    )
    audit_logger.info(
        'Admin %s exported b2b requests xlsx (%d rows, filters=%s)',
        current_user.email, len(rows), filters,
    )
    return _listing.xlsx_export(
        rows, 'b2b-requests',
        lambda: xlsx_reports.export_b2b_requests_xlsx(rows, applied_filters=summary),
        'admin.b2b_requests_list', **_listing.filter_args(filters),
    )


def _back():
    """Безпечний POST -> GET редірект назад до списку зі збереженим зрізом
    (фільтр + СТОРІНКА): без сторінки збереження в рядку на третій сторінці
    щоразу відкидало б менеджера на першу. `_listing.back_redirect`
    перечитує й перевіряє кожен параметр тим самим способом, що й роут
    списку (НЕ request.referrer -- той керований клієнтом і відкриває open
    redirect). Джерело значень -- query-string самого запиту дії: форма
    рядка несе зріз у своєму action-URL через `back_args`.
    """
    return _listing.back_redirect('admin.b2b_requests_list', _b2b_filters())


@admin_bp.route('/b2b-requests/<int:request_id>/update', methods=['POST'])
@admin_required
def b2b_request_update(request_id):
    req = db.session.get(B2BRequest, request_id)
    if not req:
        flash('Заявку не знайдено', 'error')
        return _back()

    new_status = request.form.get('status', '')
    notes = (request.form.get('admin_notes') or '').strip()
    if new_status not in {code for code, _ in B2BRequest.STATUSES}:
        flash('Невідомий статус', 'error')
        return _back()

    req.status = new_status
    req.admin_notes = notes or None
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s updated B2BRequest #%s -> %s',
            current_user.email, req.id, new_status,
        )
        flash('Заявку оновлено', 'success')
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to update B2BRequest #%s', request_id)
        flash('Помилка при збереженні', 'error')
    return _back()
