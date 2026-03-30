"""Адмін: журнал помилок."""
import logging
from datetime import datetime, timedelta, timezone

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import current_user
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.error_log import ErrorLog

audit_logger = logging.getLogger('audit')


@admin_bp.route('/error-logs')
@admin_required
def error_logs():
    # Workaround: PostgreSQL InFailedSqlTransaction після попередніх помилок
    try:
        db.session.rollback()
    except Exception:
        pass

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    error_code = request.args.get('error_code', type=int)
    resolved = request.args.get('resolved')
    days = request.args.get('days', 7, type=int)

    query = ErrorLog.query.options(joinedload(ErrorLog.user))

    if error_code:
        query = query.filter(ErrorLog.error_code == error_code)

    if resolved == 'true':
        query = query.filter(ErrorLog.resolved.is_(True))
    elif resolved == 'false':
        query = query.filter(ErrorLog.resolved.is_(False))

    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.filter(ErrorLog.created_at >= since)

    query = query.order_by(desc(ErrorLog.created_at))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    stats = ErrorLog.get_statistics(days=days)

    return render_template(
        'admin/error_logs.html',
        logs=pagination.items,
        pagination=pagination,
        stats=stats,
        filters={
            'error_code': error_code,
            'resolved': resolved,
            'days': days,
            'per_page': per_page,
        },
    )


@admin_bp.route('/error-logs/<int:error_id>')
@admin_required
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
@admin_required
def resolve_error(error_id):
    error_log = db.session.get(ErrorLog, error_id)
    if not error_log:
        flash('Запис не знайдено', 'error')
        return redirect(url_for('admin.error_logs'))

    if not error_log.resolved:
        error_log.resolved = True
        error_log.resolved_at = datetime.now(timezone.utc)
        error_log.resolved_by_id = current_user.id
        error_log.resolution_notes = request.form.get('resolution_notes', '')
        db.session.commit()
        audit_logger.info('Admin %s resolved error %s', current_user.email, error_id)
        flash('Помилку позначено як вирішену', 'success')

    return redirect(url_for('admin.error_log_detail', error_id=error_id))


@admin_bp.route('/error-logs/<int:error_id>/delete', methods=['POST'])
@admin_required
def delete_error_log(error_id):
    error_log = db.session.get(ErrorLog, error_id)
    if error_log:
        db.session.delete(error_log)
        db.session.commit()
        audit_logger.info('Admin %s deleted error log %s', current_user.email, error_id)
        flash('Запис видалено', 'success')
    return redirect(url_for('admin.error_logs'))


@admin_bp.route('/error-logs/bulk-action', methods=['POST'])
@admin_required
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
