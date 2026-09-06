"""Адмін: журнал помилок."""
import logging
from datetime import datetime, timedelta, timezone

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import current_user
from sqlalchemy import desc
from sqlalchemy.orm import joinedload

from app.admin import _listing, admin_bp
from app.rbac import permission_required
from app.extensions import db
from app.models.error_log import ErrorLog

audit_logger = logging.getLogger('audit')


# Лише зручність для випадної підказки -- НЕ валідатор: ErrorLog.error_code
# приймає будь-який http.HTTPStatus (getattr(exception, 'code', 500) у
# app/models/error_log.py пише 410/413/422/502 і т.д. так само вільно), а
# фільтр звіряє значення проти діапазону в `_error_log_filters`.
_ERROR_CODES = ('400', '401', '403', '404', '405', '429', '500', '503')
_ERROR_RESOLVED = {'false': 'Невирішені', 'true': 'Вирішені'}
# Порожнє значення = типові 7 днів, тож самої «7» у списку немає.
_ERROR_PERIODS = {'1': '1 день', '30': '30 днів', '90': '90 днів',
                  '0': 'За весь час'}
_DEFAULT_ERROR_DAYS = 7


def _error_log_filters():
    """Фільтри журналу помилок -- спільні для сторінки й експорту."""
    return {
        'q': _listing.text_arg('q'),
        # 100-599 -- межі самого HTTP-статусу, а не список у підказці: код
        # поза випадним переліком (410, 502...) усе одно мусить фільтрувати.
        'error_code': _listing.ranged_int_arg('error_code', 100, 599),
        'resolved': _listing.choice_arg('resolved', _ERROR_RESOLVED),
        'days': _listing.choice_arg('days', _ERROR_PERIODS),
    }


def _error_log_days(filters):
    """Глибина вибірки в днях (0 -- за весь час)."""
    return int(filters['days']) if filters['days'] else _DEFAULT_ERROR_DAYS


def _error_log_query(filters):
    """Записи журналу під фільтри, найновіші першими."""
    query = ErrorLog.query.options(joinedload(ErrorLog.user))
    query = _listing.apply_search(query, filters['q'], [
        ErrorLog.url, ErrorLog.error_message,
        ErrorLog.error_type, ErrorLog.ip_address,
    ])
    if filters['error_code']:
        query = query.filter(ErrorLog.error_code == int(filters['error_code']))
    if filters['resolved']:
        query = query.filter(ErrorLog.resolved.is_(filters['resolved'] == 'true'))
    days = _error_log_days(filters)
    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.filter(ErrorLog.created_at >= since)
    return query.order_by(desc(ErrorLog.created_at))


@admin_bp.route('/error-logs')
@permission_required('error_logs.view')
def error_logs():
    # Workaround: PostgreSQL InFailedSqlTransaction після попередніх помилок
    try:
        db.session.rollback()
    except Exception:
        pass

    filters = _error_log_filters()
    # Було: request.args.get('per_page', 50, type=int) -- будь-яке ціле з
    # URL напряму в paginate(), без переліку дозволених (як застерігає
    # докстрінг per_page_arg: «свавільне ?per_page=100000 інакше клало б
    # сторінку на прод-обсязі»). Сторінка не мала (і не має) власного
    # селектора розміру сторінки -- звужуємо мовчки нікому не помітно.
    per_page = _listing.per_page_arg()
    pagination = _error_log_query(filters).paginate(
        page=_listing.page_arg(),
        per_page=per_page, error_out=False,
    )

    return render_template(
        'admin/error_logs.html',
        logs=pagination.items,
        pagination=pagination,
        stats=ErrorLog.get_statistics(days=_error_log_days(filters)),
        filters=filters,
        filter_args=_listing.filter_args(filters),
        per_page=per_page,
        code_options=[(c, c) for c in _ERROR_CODES],
        resolved_options=list(_ERROR_RESOLVED.items()),
        period_options=list(_ERROR_PERIODS.items()),
    )


@admin_bp.route('/error-logs/export')
@permission_required('error_logs.export')
def error_logs_export():
    """Експорт журналу помилок у xlsx з урахуванням активних фільтрів."""
    from app.services import xlsx_reports

    filters = _error_log_filters()
    # Стелю рядків міряємо COUNT-ом ДО вибірки: інакше зріз спершу
    # піднімався б у пам'ять цілком і лише потім отримував відмову.
    logs, refusal = _listing.export_query(
        _error_log_query(filters), 'admin.error_logs', **_listing.filter_args(filters),
    )
    if refusal:
        return refusal
    days = _error_log_days(filters)
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Код', filters['error_code'] or 'Усі'),
            ('Стан', _ERROR_RESOLVED.get(filters['resolved'], 'Усі')),
            ('Період', 'За весь час' if days == 0 else f'останні {days} дн.'),
        ],
        len(logs),
    )
    audit_logger.info(
        'Admin %s exported error logs xlsx (%d rows, filters=%s)',
        current_user.email, len(logs), filters,
    )
    return _listing.xlsx_export(
        logs, 'error-logs',
        lambda: xlsx_reports.export_error_logs_xlsx(logs, applied_filters=summary),
        'admin.error_logs', **_listing.filter_args(filters),
    )


@admin_bp.route('/error-logs/<int:error_id>')
@permission_required('error_logs.view')
def error_log_detail(error_id):
    error_log = db.session.get(ErrorLog, error_id)
    if not error_log:
        flash('Запис не знайдено', 'error')
        return redirect(url_for('admin.error_logs'))

    return render_template(
        'admin/error_log_detail.html',
        error_log=error_log,
        request_data=error_log.get_request_data(),
        headers=error_log.get_headers(),
    )


@admin_bp.route('/error-logs/<int:error_id>/resolve', methods=['POST'])
@permission_required('error_logs.manage')
def resolve_error(error_id):
    error_log = db.session.get(ErrorLog, error_id)
    if not error_log:
        flash('Запис не знайдено', 'error')
        return redirect(url_for('admin.error_logs'))

    if error_log.resolved:
        error_log.resolved = False
        error_log.resolved_at = None
        error_log.resolved_by_id = None
        error_log.resolution_notes = None
        db.session.commit()
        audit_logger.info('Admin %s reopened error %s', current_user.email, error_id)
        flash('Помилку повернено у статус "Відкрита"', 'info')
    else:
        error_log.resolved = True
        error_log.resolved_at = datetime.now(timezone.utc)
        error_log.resolved_by_id = current_user.id
        error_log.resolution_notes = request.form.get('resolution_notes', '')
        db.session.commit()
        audit_logger.info('Admin %s resolved error %s', current_user.email, error_id)
        flash('Помилку позначено як вирішену', 'success')

    referer = request.referrer
    if referer and 'error-logs' in referer and str(error_id) not in referer:
        return redirect(url_for('admin.error_logs'))
    return redirect(url_for('admin.error_log_detail', error_id=error_id))


@admin_bp.route('/error-logs/<int:error_id>/delete', methods=['POST'])
@permission_required('error_logs.delete')
def delete_error_log(error_id):
    error_log = db.session.get(ErrorLog, error_id)
    if error_log:
        db.session.delete(error_log)
        db.session.commit()
        audit_logger.info('Admin %s deleted error log %s', current_user.email, error_id)
        flash('Запис видалено', 'success')
    return redirect(url_for('admin.error_logs'))


@admin_bp.route('/error-logs/bulk-action', methods=['POST'])
@permission_required('error_logs.delete')
def error_logs_bulk_action():
    action = request.form.get('action')
    error_ids = request.form.getlist('error_ids[]')

    if not error_ids:
        return jsonify({'success': False, 'message': 'Не вибрано жодного запису'}), 400

    if len(error_ids) > 500:
        return jsonify({'success': False, 'message': 'Максимум 500 записів за раз'}), 400

    if action == 'resolve':
        ErrorLog.query.filter(ErrorLog.id.in_(error_ids)).update(
            {
                'resolved': True,
                'resolved_at': datetime.now(timezone.utc),
                'resolved_by_id': current_user.id,
            },
            synchronize_session=False,
        )
        db.session.commit()
        return jsonify({'success': True, 'message': f'Вирішено: {len(error_ids)}'})

    if action == 'delete':
        ErrorLog.query.filter(ErrorLog.id.in_(error_ids)).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({'success': True, 'message': f'Видалено: {len(error_ids)}'})

    return jsonify({'success': False, 'message': 'Невідома дія'}), 400
