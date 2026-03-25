import logging
from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import current_user
from sqlalchemy import func as sa_func

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.email_log import EmailLog

audit_logger = logging.getLogger('audit')


@admin_bp.route('/notifications')
@admin_required
def notifications():
    """Dashboard: stats, recent sends, scheduler status."""
    total = db.session.query(sa_func.count(EmailLog.id)).scalar() or 0
    sent = db.session.query(sa_func.count(EmailLog.id)).filter(
        EmailLog.status == 'sent'
    ).scalar() or 0
    failed = db.session.query(sa_func.count(EmailLog.id)).filter(
        EmailLog.status == 'failed'
    ).scalar() or 0
    pending = db.session.query(sa_func.count(EmailLog.id)).filter(
        EmailLog.status == 'pending'
    ).scalar() or 0

    stats = {'total': total, 'sent': sent, 'failed': failed, 'pending': pending}

    recent = EmailLog.query.order_by(
        EmailLog.created_at.desc()
    ).limit(20).all()

    from app.services.scheduler_service import scheduler
    scheduler_running = scheduler.running
    jobs = scheduler.get_jobs() if scheduler_running else []

    mail_configured = bool(
        current_app.config.get('MAIL_USERNAME')
        and current_app.config.get('MAIL_PASSWORD')
    )

    return render_template(
        'admin/notifications.html',
        stats=stats,
        recent=recent,
        scheduler_running=scheduler_running,
        jobs=jobs,
        mail_configured=mail_configured,
    )


@admin_bp.route('/notifications/log')
@admin_required
def notifications_log():
    """Full email log with filtering."""
    status_filter = request.args.get('status', '')
    trigger_filter = request.args.get('trigger', '')
    page = request.args.get('page', 1, type=int)

    query = EmailLog.query
    if status_filter:
        query = query.filter(EmailLog.status == status_filter)
    if trigger_filter:
        query = query.filter(EmailLog.trigger == trigger_filter)

    pagination = query.order_by(
        EmailLog.created_at.desc()
    ).paginate(page=page, per_page=50, error_out=False)

    return render_template(
        'admin/notifications_log.html',
        pagination=pagination,
        logs=pagination.items,
        filters={'status': status_filter, 'trigger': trigger_filter},
    )


@admin_bp.route('/notifications/test', methods=['POST'])
@admin_required
def notifications_test():
    """Send a test email."""
    to = request.form.get('to', '').strip()
    if not to:
        to = current_user.email

    from app.services.email_service import EmailService
    try:
        EmailService.send_test_email(to)
        audit_logger.info('Admin %s sent test email to %s', current_user.email, to)
        flash(f'Тестовий лист відправлено на {to}', 'success')
    except Exception as exc:
        flash(f'Помилка: {exc}', 'error')

    return redirect(url_for('admin.notifications'))


@admin_bp.route('/notifications/scheduler/pause', methods=['POST'])
@admin_required
def scheduler_pause():
    from app.services.scheduler_service import scheduler
    scheduler.pause()
    audit_logger.info('Admin %s paused scheduler', current_user.email)
    flash('Планувальник призупинено', 'info')
    return redirect(url_for('admin.notifications'))


@admin_bp.route('/notifications/scheduler/resume', methods=['POST'])
@admin_required
def scheduler_resume():
    from app.services.scheduler_service import scheduler
    scheduler.resume()
    audit_logger.info('Admin %s resumed scheduler', current_user.email)
    flash('Планувальник відновлено', 'success')
    return redirect(url_for('admin.notifications'))
