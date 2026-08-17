import logging
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy import func as sa_func

from app.admin import _listing, admin_bp
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


def _email_log_filters():
    """Фільтри лог-журналу листів -- спільні для сторінки й експорту."""
    return {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', dict(EmailLog.STATUSES)),
        'trigger': _listing.choice_arg('trigger', dict(EmailLog.TRIGGERS)),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
    }


def _email_log_query(filters):
    """Записи журналу під фільтри, найновіші першими."""
    query = _listing.apply_search(EmailLog.query, filters['q'], [
        EmailLog.to_email, EmailLog.subject,
        EmailLog.template_name, EmailLog.error_message,
    ])
    if filters['status']:
        query = query.filter(EmailLog.status == filters['status'])
    if filters['trigger']:
        query = query.filter(EmailLog.trigger == filters['trigger'])
    query = _listing.apply_date_range(
        query, EmailLog.created_at, filters['date_from'], filters['date_to'],
    )
    return query.order_by(EmailLog.created_at.desc())


@admin_bp.route('/notifications/log')
@admin_required
def notifications_log():
    """Full email log with filtering."""
    filters = _email_log_filters()
    pagination = _email_log_query(filters).paginate(
        page=request.args.get('page', 1, type=int), per_page=50, error_out=False,
    )
    return render_template(
        'admin/notifications_log.html',
        pagination=pagination,
        logs=pagination.items,
        filters=filters,
        filter_args=_listing.filter_args(filters),
        status_options=EmailLog.STATUSES,
        trigger_options=EmailLog.TRIGGERS,
    )


@admin_bp.route('/notifications/log/export')
@admin_required
def notifications_log_export():
    """Експорт журналу листів у xlsx з урахуванням активних фільтрів.

    Головний кейс -- розбір «чому людині не дійшов лист»: у файлі видно
    статус, тригер, кількість ретраїв і текст помилки SMTP.
    """
    from app.services import xlsx_reports

    filters = _email_log_filters()
    logs = _email_log_query(filters).all()
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Статус', dict(EmailLog.STATUSES).get(filters['status'], 'Усі')),
            ('Тригер', dict(EmailLog.TRIGGERS).get(filters['trigger'], 'Усі')),
            ('Дата листа', _listing.date_range_label(filters)),
        ],
        len(logs),
    )
    audit_logger.info(
        'Admin %s exported email log xlsx (%d rows, filters=%s)',
        current_user.email, len(logs), filters,
    )
    return _listing.xlsx_export(
        logs, 'email-log',
        lambda: xlsx_reports.export_email_logs_xlsx(logs, applied_filters=summary),
        'admin.notifications_log', **_listing.filter_args(filters),
    )


@admin_bp.route('/notifications/log/<int:log_id>/resend', methods=['POST'])
@admin_required
def notifications_log_resend(log_id):
    """Ручний resend конкретного failed-листа (адмін-кнопка).
    Без cutoff/MAX_RETRIES обмежень -- адмін явно тисне.
    """
    from app.services.email_service import EmailService
    ok, msg = EmailService.manual_resend(log_id)
    audit_logger.info(
        'Admin %s manual-resent EmailLog id=%s -> %s',
        current_user.email, log_id, 'OK' if ok else 'FAIL'
    )
    flash(msg, 'success' if ok else 'error')
    # Повертаємось туди, звідки прийшли (notifications dashboard або full-log).
    return redirect(request.referrer or url_for('admin.notifications_log'))


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
        full_name = 'Олена Шевченко'
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
        payment_status_label = 'Не оплачено'
        payment_amount = 12500
        payment_method = 'liqpay'
        payment_method_label = 'Онлайн-оплата (LiqPay)'
        place_number = None
        phone = '+380671234567'
        specialty = 'Дерматолог'
        workplace = 'Клініка "Медіка", Київ'
        has_discount = False
        promo_code = None
        STATUSES = [
            ('pending', 'Очікує'),
            ('confirmed', 'Підтверджено'),
            ('cancelled', 'Скасовано'),
            ('completed', 'Завершено'),
        ]

    user = MockUser()
    event = MockEvent()
    reg = MockRegistration()

    class MockRegPaid(MockRegistration):
        id = 2
        payment_status = 'paid'
        payment_status_label = 'Оплачено'
        payment_amount = 12500
        place_number = 7

    reg_paid = MockRegPaid()

    class MockPromo:
        code = 'NEXT-A7K3XY'
        discount_label = '10%'
        valid_until = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)

    # Прев'ю листа про оплату показує всі блоки одразу (кабінет, календар,
    # промокод, реферальне посилання) -- інакше редактор бачив би порожній
    # каркас і не міг оцінити довжину листа.
    # Домен для прев'ю беремо з налаштувань, а не зашиваємо: зашитий устарів
    # при переїзді на iprm.space, і редактор бачив у прев'ю чужий бренд.
    from app.models.site_settings import SiteSettings
    preview_base = (SiteSettings.get().website_url or 'https://iprm.space').rstrip('/')

    mock_payment_ctx = {
        'needs_account': False,
        'account_url': f'{preview_base}/auth/account',
        'course_url': f'{preview_base}/courses/prp',
        'courses_url': f'{preview_base}/courses',
        'gcal_url': 'https://calendar.google.com/calendar/render?action=TEMPLATE',
        'has_ics': True,
        'promo': MockPromo(),
        'referral_link': f'{preview_base}/?ref=u1a2b3c4d&utm_source=referral',
    }

    class MockCertificate:
        number = '2026-2738-0001234-000001'
        cpd_points = 10
        event_date = MockEvent.start_date
        event_title = MockEvent.title

    class MockComment:
        author_name = 'Ігор Петренко'
        email = 'igor@example.com'
        body = 'Дуже корисна стаття, дякую за детальний розбір протоколу!'
        created_at = datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc)

    class MockPost:
        title = 'PRP у трихології: покрокова методика'

    class MockCourse:
        title = 'PRP-терапія: сучасні протоколи'

    class MockCourseRequest:
        email = 'client@example.com'
        phone = '+380671234567'
        message = 'Цікавить корпоративне навчання для 5 лікарів нашої клініки.'
        created_at = datetime(2026, 4, 12, 9, 15, tzinfo=timezone.utc)

    class MockB2BRequest:
        full_name = 'Марія Коваленко'
        email = 'b2b@clinic.example.com'
        phone = '+380509876543'
        team_size_label = '6–10 осіб'
        created_at = datetime(2026, 4, 11, 11, 0, tzinfo=timezone.utc)

    class MockAppliedPromo:
        code = 'ФАРМА-2026'
        discount_label = '20%'

    class MockRegPaidPromo(MockRegistration):
        """Оплата зі знижкою -- показує в прев'ю рядки промокоду."""
        id = 3
        payment_status = 'paid'
        payment_status_label = 'Оплачено'
        payment_amount = 10000
        place_number = 7
        has_discount = True
        discount_amount = 2500
        amount_before_discount = 12500
        promo_code = MockAppliedPromo()

    reg_paid_promo = MockRegPaidPromo()

    reg.user = user  # admin_event_notification renders registration.user
    reg_paid_promo.user = user

    certificate = MockCertificate()
    comment = MockComment()
    post = MockPost()
    course = MockCourse()
    course_request = MockCourseRequest()
    b2b_request = MockB2BRequest()
    mock_admin_url = f'{preview_base}/admin'
    mock_materials_items = [
        {'sku': 'NDL-21', 'name': 'Голка 21G', 'quantity_reserved': 5},
        {'sku': 'ROLL-DENTAL', 'name': 'Валик ватний', 'quantity_reserved': 12},
        {'sku': 'GLOVE-M', 'name': 'Рукавички M', 'quantity_reserved': 20},
    ]

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
            'subject': f'Ви в списку учасників: {event.title}',
            'html': render_template('emails/payment_confirmed.html',
                                    user=user, event=event, registration=reg_paid,
                                    **mock_payment_ctx),
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
        {
            'key': 'email-confirm',
            'label': 'Підтвердження email',
            'template_name': 'email_confirm.html',
            'trigger': 'email_confirm',
            'subject': 'Підтвердіть ваш email | IPRM',
            'html': render_template('emails/email_confirm.html',
                                    user=user, confirm_url=f'{preview_base}/auth/confirm/example'),
        },
        {
            'key': 'password-reset',
            'label': 'Відновлення паролю',
            'template_name': 'password_reset.html',
            'trigger': 'password_reset',
            'subject': 'Відновлення паролю | IPRM',
            'html': render_template('emails/password_reset.html',
                                    user=user, reset_url=f'{preview_base}/auth/reset/example'),
        },
        {
            'key': 'completion-link',
            'label': 'Завершення реєстрації',
            'template_name': 'completion_link.html',
            'trigger': 'registration',
            'subject': f'Завершіть реєстрацію: {event.title}',
            'html': render_template('emails/completion_link.html',
                                    user=user, event=event,
                                    complete_url=f'{preview_base}/registration/complete/example'),
        },
        {
            'key': 'certificate',
            'label': 'Сертифікат видано',
            'template_name': 'certificate_issued.html',
            'trigger': 'certificate',
            'subject': f'Ваш сертифікат готовий: {certificate.event_title}',
            'html': render_template('emails/certificate_issued.html',
                                    user=user, certificate=certificate,
                                    account_url=f'{preview_base}/auth/account'),
        },
        {
            'key': 'course-request-received',
            'label': 'Запит на курс: клієнту',
            'template_name': 'course_request_received.html',
            'trigger': 'course_request',
            'subject': f'Ми отримали ваш запит: {course.title}',
            'html': render_template('emails/course_request_received.html',
                                    request_obj=course_request, course=course,
                                    course_url=f'{preview_base}/courses/prp'),
        },
        {
            'key': 'course-request-admin',
            'label': 'Запит на курс: адміну',
            'template_name': 'course_request_notification.html',
            'trigger': 'course_request',
            'subject': f'Новий запит на курс: {course.title}',
            'html': render_template('emails/course_request_notification.html',
                                    request_obj=course_request, course=course,
                                    admin_url=mock_admin_url),
        },
        {
            'key': 'b2b-request',
            'label': 'B2B-заявка: адміну',
            'template_name': 'b2b_request_notification.html',
            'trigger': 'course_request',
            'subject': 'Нова B2B-заявка',
            'html': render_template('emails/b2b_request_notification.html',
                                    request_obj=b2b_request, admin_url=mock_admin_url),
        },
        {
            'key': 'blog-comment',
            'label': 'Коментар у блозі: адміну',
            'template_name': 'blog_comment_notification.html',
            'trigger': 'blog_comment',
            'subject': f'Новий коментар: {post.title}',
            'html': render_template('emails/blog_comment_notification.html',
                                    comment=comment, post=post, admin_url=mock_admin_url),
        },
        {
            'key': 'admin-event',
            'label': 'Admin-сповіщення про подію',
            'template_name': 'admin_event_notification.html',
            'trigger': 'status_change',
            'subject': f'Нова реєстрація: {event.title} – {user.full_name}',
            'html': render_template('emails/admin_event_notification.html',
                                    event=event, registration=reg,
                                    kind_label='Нова реєстрація',
                                    admin_url=mock_admin_url),
        },
        {
            'key': 'admin-payment',
            'label': 'Admin-сповіщення про оплату',
            'template_name': 'admin_event_notification.html',
            'trigger': 'payment',
            'subject': f'Оплата 10000 UAH: {event.title} – {user.full_name}',
            'html': render_template('emails/admin_event_notification.html',
                                    event=event, registration=reg_paid_promo,
                                    kind_label='Підтверджена оплата',
                                    admin_url=mock_admin_url),
        },
        {
            'key': 'materials-reminder',
            'label': 'Матеріали: нагадування',
            'template_name': 'materials_actuals_reminder.html',
            'trigger': 'materials',
            'subject': f'Внесіть фактичні матеріали: {event.title}',
            'html': render_template('emails/materials_actuals_reminder.html',
                                    event_title=event.title, event_date='15.04.2026',
                                    items=mock_materials_items,
                                    admin_url=f'{preview_base}/admin/instances/1/materials'),
        },
        {
            'key': 'backup-failure',
            'label': 'Помилка бекапу',
            'template_name': 'backup_failure.html',
            'trigger': 'backup_failure',
            'subject': 'IPRM: помилка автоматичного бекапу БД',
            'html': render_template('emails/backup_failure.html',
                                    error_message='Connection to backup storage timed out after 30s',
                                    admin_url=mock_admin_url),
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
