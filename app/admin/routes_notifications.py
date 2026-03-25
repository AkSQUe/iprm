import logging
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy import func as sa_func

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.email_log import EmailLog, MAX_RETRIES
from app.models.email_settings import EmailSettings
from app.services.email_service import CIRCUIT_BREAKER_THRESHOLD

audit_logger = logging.getLogger('audit')


@admin_bp.route('/notifications')
@admin_required
def notifications():
    """Dashboard: stats, settings form, recent sends, scheduler."""
    settings = EmailSettings.get()

    row = db.session.query(
        sa_func.count(EmailLog.id).label('total'),
        sa_func.count(sa_func.nullif(EmailLog.status != 'sent', True)).label('sent'),
        sa_func.count(sa_func.nullif(EmailLog.status != 'failed', True)).label('failed'),
        sa_func.count(sa_func.nullif(EmailLog.status != 'pending', True)).label('pending'),
    ).one()
    stats = {'total': row.total, 'sent': row.sent, 'failed': row.failed, 'pending': row.pending}

    recent = EmailLog.query.order_by(
        EmailLog.created_at.desc()
    ).limit(20).all()

    from datetime import datetime, timedelta, timezone
    from app.services.scheduler_service import scheduler
    scheduler_running = scheduler.running
    jobs = scheduler.get_jobs() if scheduler_running else []

    # Queue health stats
    cutoff_10m = datetime.now(timezone.utc) - timedelta(minutes=10)
    recent_failures = EmailLog.query.filter(
        EmailLog.status == 'failed',
        EmailLog.created_at >= cutoff_10m,
        EmailLog.trigger != 'test',
    ).count()
    retryable = EmailLog.query.filter(
        EmailLog.status == 'failed',
        EmailLog.retry_count < MAX_RETRIES,
        EmailLog.trigger != 'test',
        EmailLog.created_at >= datetime.now(timezone.utc) - timedelta(hours=1),
    ).count()
    circuit_open = recent_failures >= CIRCUIT_BREAKER_THRESHOLD

    queue_health = {
        'recent_failures': recent_failures,
        'retryable': retryable,
        'circuit_open': circuit_open,
    }

    return render_template(
        'admin/notifications.html',
        settings=settings,
        stats=stats,
        recent=recent,
        scheduler_running=scheduler_running,
        jobs=jobs,
        queue_health=queue_health,
    )


@admin_bp.route('/notifications/settings', methods=['POST'])
@admin_required
def notifications_settings():
    """Save SMTP settings to DB."""
    settings = EmailSettings.get()

    settings.smtp_server = request.form.get('smtp_server', '').strip()
    try:
        settings.smtp_port = int(request.form.get('smtp_port') or 465)
    except (ValueError, TypeError):
        settings.smtp_port = 465
    settings.smtp_use_ssl = request.form.get('smtp_use_ssl') == 'on'
    settings.smtp_use_tls = request.form.get('smtp_use_tls') == 'on'
    settings.smtp_username = request.form.get('smtp_username', '').strip()

    new_password = request.form.get('smtp_password', '').strip()
    if new_password:
        settings.smtp_password = new_password

    settings.default_sender = request.form.get('default_sender', '').strip()
    settings.sender_name = request.form.get('sender_name', 'IPRM').strip()
    want_enabled = request.form.get('is_enabled') == 'on'

    if want_enabled:
        missing = []
        if not settings.smtp_server:
            missing.append('SMTP сервер')
        if not settings.smtp_username:
            missing.append('Логін')
        if not settings.has_password and not new_password:
            missing.append('Пароль')
        if not settings.default_sender:
            missing.append('Email відправника')
        if missing:
            flash(f'Неможливо увімкнути: заповніть {", ".join(missing)}', 'error')
            want_enabled = False

    settings.is_enabled = want_enabled
    settings.reminder_days = request.form.get('reminder_days', '7,3,1').strip()

    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s updated email settings: server=%s enabled=%s',
            current_user.email, settings.smtp_server, settings.is_enabled,
        )
        flash('Налаштування збережено', 'success')
    except Exception:
        db.session.rollback()
        flash('Помилка збереження', 'error')

    return redirect(url_for('admin.notifications'))


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
    except RuntimeError as exc:
        flash(str(exc), 'error')
    except Exception as exc:
        error_msg = str(exc)
        if 'Authentication' in error_msg or '535' in error_msg:
            flash('SMTP: невірний логін або пароль. Перевірте налаштування.', 'error')
        elif 'Connection' in error_msg or 'timed out' in error_msg:
            flash(f'SMTP: не вдалося підключитися до сервера. {error_msg}', 'error')
        else:
            flash(f'Помилка відправки: {error_msg}', 'error')

    return redirect(url_for('admin.notifications'))


@admin_bp.route('/notifications/templates')
@admin_required
def notifications_templates():
    """Preview all email templates with mock data."""
    from datetime import datetime, timezone

    class MockUser:
        first_name = 'Олена'
        last_name = 'Шевченко'
        email = 'olena@example.com'

    class MockEvent:
        title = 'PRP-терапія: сучасні протоколи'
        start_date = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)
        location = 'Київ, вул. Хрещатик 1, клініка IPRM'
        price = 12500
        online_link = 'https://zoom.us/j/example'

    class MockRegistration:
        id = 1
        payment_status = 'unpaid'
        payment_amount = 12500
        STATUSES = [
            ('pending', 'Очікує'),
            ('confirmed', 'Підтверджено'),
            ('cancelled', 'Скасовано'),
            ('completed', 'Завершено'),
        ]

    user = MockUser()
    event = MockEvent()
    reg = MockRegistration()

    class MockRegPaid:
        id = 2
        payment_status = 'paid'
        payment_amount = 12500
        STATUSES = MockRegistration.STATUSES

    reg_paid = MockRegPaid()

    templates = [
        {
            'key': 'test',
            'label': 'Тестовий',
            'template_name': 'test.html',
            'trigger': 'test',
            'subject': 'IPRM: Тестовий лист',
            'html': render_template('emails/test.html', to_email='admin@iprm.space'),
        },
        {
            'key': 'registration',
            'label': 'Реєстрація',
            'template_name': 'registration_confirmed.html',
            'trigger': 'registration',
            'subject': f'Реєстрацію підтверджено: {event.title}',
            'html': render_template('emails/registration_confirmed.html',
                                    user=user, event=event, registration=reg),
        },
        {
            'key': 'payment',
            'label': 'Оплата',
            'template_name': 'payment_confirmed.html',
            'trigger': 'payment',
            'subject': f'Оплату підтверджено: {event.title}',
            'html': render_template('emails/payment_confirmed.html',
                                    user=user, event=event, registration=reg_paid),
        },
        {
            'key': 'reminder-7',
            'label': 'Нагадування (7 дн.)',
            'template_name': 'course_reminder.html',
            'trigger': 'reminder',
            'subject': f'Нагадування: {event.title} через 7 дн.',
            'html': render_template('emails/course_reminder.html',
                                    user=user, event=event, registration=reg, days_until=7),
        },
        {
            'key': 'reminder-1',
            'label': 'Нагадування (завтра)',
            'template_name': 'course_reminder.html',
            'trigger': 'reminder',
            'subject': f'Нагадування: {event.title} через 1 дн.',
            'html': render_template('emails/course_reminder.html',
                                    user=user, event=event, registration=reg, days_until=1),
        },
        {
            'key': 'status-confirmed',
            'label': 'Статус: підтверджено',
            'template_name': 'status_changed.html',
            'trigger': 'status_change',
            'subject': f'Статус реєстрації змінено: {event.title}',
            'html': render_template('emails/status_changed.html',
                                    user=user, event=event, registration=reg,
                                    old_status='pending', new_status='confirmed',
                                    new_status_label='Підтверджено'),
        },
        {
            'key': 'status-cancelled',
            'label': 'Статус: скасовано',
            'template_name': 'status_changed.html',
            'trigger': 'status_change',
            'subject': f'Статус реєстрації змінено: {event.title}',
            'html': render_template('emails/status_changed.html',
                                    user=user, event=event, registration=reg,
                                    old_status='confirmed', new_status='cancelled',
                                    new_status_label='Скасовано'),
        },
        {
            'key': 'status-completed',
            'label': 'Статус: завершено',
            'template_name': 'status_changed.html',
            'trigger': 'status_change',
            'subject': f'Статус реєстрації змінено: {event.title}',
            'html': render_template('emails/status_changed.html',
                                    user=user, event=event, registration=reg,
                                    old_status='confirmed', new_status='completed',
                                    new_status_label='Завершено'),
        },
    ]

    return render_template('admin/notifications_templates.html', templates=templates)


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
