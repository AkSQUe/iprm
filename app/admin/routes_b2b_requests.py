"""Admin: заявки на корпоративне навчання (B2B, блок "Для команд і клінік")."""
import logging

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.b2b_request import B2BRequest

audit_logger = logging.getLogger('audit')


@admin_bp.route('/b2b-requests')
@admin_required
def b2b_requests_list():
    status = request.args.get('status', '')
    query = B2BRequest.query
    if status:
        query = query.filter_by(status=status)
    requests_list = query.order_by(B2BRequest.created_at.desc()).all()
    new_count = B2BRequest.query.filter_by(status='new').count()
    return render_template(
        'admin/b2b_requests.html',
        requests=requests_list,
        active_status=status,
        new_count=new_count,
    )


@admin_bp.route('/b2b-requests/<int:request_id>/update', methods=['POST'])
@admin_required
def b2b_request_update(request_id):
    req = db.session.get(B2BRequest, request_id)
    if not req:
        flash('Заявку не знайдено', 'error')
        return redirect(url_for('admin.b2b_requests_list'))

    new_status = request.form.get('status', '')
    notes = (request.form.get('admin_notes') or '').strip()
    if new_status not in {code for code, _ in B2BRequest.STATUSES}:
        flash('Невідомий статус', 'error')
        return redirect(url_for('admin.b2b_requests_list'))

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
    return redirect(url_for('admin.b2b_requests_list', status=request.args.get('status', '')))
