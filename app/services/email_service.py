"""
Email sending service with threaded delivery, retry logic, and audit logging.

Protection system:
- Stale pending cleanup: emails stuck >5 min in "pending" are marked failed.
- Retry with backoff: transient SMTP failures retried up to 3 times.
  Retry re-sends the saved html_body, not re-renders the template.
- Permanent failure detection: auth errors, bad addresses are never retried.
- Deduplication: same trigger+registration within 60s window is skipped.
- Circuit breaker: if >5 failures in last 10 min, new sends are paused.
- Test emails are always synchronous and never retried.
- Thread-safe: SMTP config is passed as a dict, never mutated on app.config.
"""
import logging
import re
import smtplib
from datetime import datetime, timedelta, timezone
from threading import Thread

from flask import current_app, render_template
from flask_mail import Message

from app.extensions import db
from app.models.email_log import EmailLog, MAX_RETRIES, STALE_PENDING_MINUTES

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r'<[^>]+>')
_WHITESPACE_RE = re.compile(r'\n\s*\n')

DEDUP_WINDOW_SECONDS = 60

CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_WINDOW_MINUTES = 10

# Timeout (seconds) for synchronous SMTP operations (test email).
SMTP_TIMEOUT_SECONDS = 15


def _html_to_plaintext(html):
    """Minimal HTML-to-text conversion for email plain text fallback."""
    text = html.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
    text = _HTML_TAG_RE.sub('', text)
    text = _WHITESPACE_RE.sub('\n\n', text)
    return text.strip()


def _get_smtp_config(app):
    """Read SMTP settings from DB and return as an isolated dict (thread-safe)."""
    from app.models.email_settings import EmailSettings
    settings = EmailSettings.get()
    config = {
        'server': settings.smtp_server,
        'port': settings.smtp_port,
        'use_ssl': settings.smtp_use_ssl,
        'use_tls': settings.smtp_use_tls,
        'username': settings.smtp_username,
        'password': settings.smtp_password,
        'is_enabled': settings.is_enabled,
        'has_password': settings.has_password,
    }
    if settings.sender_name and settings.default_sender:
        config['sender'] = (settings.sender_name, settings.default_sender)
    elif settings.default_sender:
        config['sender'] = settings.default_sender
    else:
        config['sender'] = settings.smtp_username
    return config


def _smtp_send(msg, smtp_cfg):
    """Send a flask_mail.Message using the given SMTP config dict.

    This avoids mutating app.config, making it safe to call from any thread.
    """
    host_cls = smtplib.SMTP_SSL if smtp_cfg['use_ssl'] else smtplib.SMTP
    with host_cls(smtp_cfg['server'], smtp_cfg['port'], timeout=SMTP_TIMEOUT_SECONDS) as host:
        host.ehlo()
        if smtp_cfg['use_tls'] and not smtp_cfg['use_ssl']:
            host.starttls()
            host.ehlo()
        if smtp_cfg['username'] and smtp_cfg['password']:
            host.login(smtp_cfg['username'], smtp_cfg['password'])
        host.sendmail(smtp_cfg['username'], msg.send_to, msg.as_bytes())


class EmailService:

    @staticmethod
    def _check_circuit_breaker():
        """Return True if too many recent failures (circuit open)."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=CIRCUIT_BREAKER_WINDOW_MINUTES)
        recent_failures = EmailLog.query.filter(
            EmailLog.status == 'failed',
            EmailLog.created_at >= cutoff,
            EmailLog.trigger != 'test',
        ).count()
        return recent_failures >= CIRCUIT_BREAKER_THRESHOLD

    @staticmethod
    def _check_duplicate(to, trigger, registration_id):
        """Return True if a duplicate email was sent/queued recently."""
        if not trigger or trigger == 'test':
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=DEDUP_WINDOW_SECONDS)
        query = EmailLog.query.filter(
            EmailLog.to_email == to,
            EmailLog.trigger == trigger,
            EmailLog.created_at >= cutoff,
            EmailLog.status.in_(['pending', 'sent']),
        )
        if registration_id:
            query = query.filter(EmailLog.registration_id == registration_id)
        return query.first() is not None

    @staticmethod
    def send_email(to, subject, template_name, context=None,
                   trigger=None, registration_id=None):
        """
        Render email template and send via SMTP in background thread.

        Guards: disabled check, deduplication, circuit breaker.
        Returns EmailLog instance (status may still be 'pending' if async).
        Returns None if dedup skipped.
        """
        app = current_app._get_current_object()
        ctx = context or {}

        with app.app_context():
            smtp_cfg = _get_smtp_config(app)

        if not smtp_cfg['is_enabled']:
            logger.info('Email disabled, skipping: %s -> %s', template_name, to)
            log_entry = EmailLog(
                to_email=to,
                subject=subject,
                template_name=template_name,
                status='failed',
                error_message='Email sending is disabled in settings',
                trigger=trigger,
                registration_id=registration_id,
            )
            db.session.add(log_entry)
            db.session.commit()
            return log_entry

        if EmailService._check_duplicate(to, trigger, registration_id):
            logger.info('Dedup: skipping %s -> %s (trigger=%s reg=%s)',
                        template_name, to, trigger, registration_id)
            return None

        if EmailService._check_circuit_breaker():
            logger.warning('Circuit breaker OPEN: skipping %s -> %s', template_name, to)
            log_entry = EmailLog(
                to_email=to,
                subject=subject,
                template_name=template_name,
                status='failed',
                error_message='Circuit breaker: too many recent failures, sending paused',
                trigger=trigger,
                registration_id=registration_id,
            )
            db.session.add(log_entry)
            db.session.commit()
            return log_entry

        try:
            html_body = render_template(f'emails/{template_name}.html', **ctx)
        except Exception as exc:
            log_entry = EmailLog(
                to_email=to,
                subject=subject,
                template_name=template_name,
                status='failed',
                error_message=f'Template render error: {str(exc)[:400]}',
                trigger=trigger,
                registration_id=registration_id,
            )
            db.session.add(log_entry)
            db.session.commit()
            logger.exception('Failed to render email template %s', template_name)
            return log_entry

        log_entry = EmailLog(
            to_email=to,
            subject=subject,
            template_name=template_name,
            status='pending',
            trigger=trigger,
            registration_id=registration_id,
            html_body=html_body,
        )
        db.session.add(log_entry)
        db.session.commit()

        plain_body = _html_to_plaintext(html_body)
        msg = Message(
            subject=subject,
            recipients=[to],
            html=html_body,
            body=plain_body,
            sender=smtp_cfg['sender'],
        )

        thread = Thread(
            target=EmailService._send_in_thread,
            args=(app, msg, log_entry.id, smtp_cfg),
        )
        thread.daemon = True
        thread.start()

        return log_entry

    @staticmethod
    def _send_in_thread(app, msg, log_id, smtp_cfg):
        """Execute SMTP send in background thread with isolated config."""
        with app.app_context():
            log_entry = db.session.get(EmailLog, log_id)
            if not log_entry:
                logger.error('EmailLog %s not found in thread', log_id)
                return
            try:
                _smtp_send(msg, smtp_cfg)
                log_entry.status = 'sent'
                log_entry.sent_at = datetime.now(timezone.utc)
                logger.info('Email sent to %s: %s', msg.recipients[0], msg.subject)
            except Exception as exc:
                log_entry.status = 'failed'
                log_entry.error_message = str(exc)[:500]
                logger.exception('Failed to send email to %s', msg.recipients[0])
            finally:
                db.session.commit()

    # ---- Convenience senders ----

    @staticmethod
    def send_registration_confirmation(registration):
        event = registration.event
        user = registration.user
        return EmailService.send_email(
            to=user.email,
            subject=f'Реєстрацію підтверджено: {event.title}',
            template_name='registration_confirmed',
            context={'user': user, 'event': event, 'registration': registration},
            trigger='registration',
            registration_id=registration.id,
        )

    @staticmethod
    def send_email_confirmation(user, confirm_url):
        return EmailService.send_email(
            to=user.email,
            subject='Підтвердіть ваш email | IPRM',
            template_name='email_confirm',
            context={'user': user, 'confirm_url': confirm_url},
            trigger='email_confirm',
        )

    @staticmethod
    def send_payment_confirmation(registration):
        event = registration.event
        user = registration.user
        return EmailService.send_email(
            to=user.email,
            subject=f'Оплату підтверджено: {event.title}',
            template_name='payment_confirmed',
            context={'user': user, 'event': event, 'registration': registration},
            trigger='payment',
            registration_id=registration.id,
        )

    @staticmethod
    def send_course_reminder(registration, days_until):
        event = registration.event
        user = registration.user
        return EmailService.send_email(
            to=user.email,
            subject=f'Нагадування: {event.title} через {days_until} дн.',
            template_name='course_reminder',
            context={
                'user': user, 'event': event,
                'registration': registration, 'days_until': days_until,
            },
            trigger='reminder',
            registration_id=registration.id,
        )

    @staticmethod
    def send_status_change(registration, old_status, new_status):
        event = registration.event
        user = registration.user
        label = dict(registration.STATUSES).get(new_status, new_status)
        return EmailService.send_email(
            to=user.email,
            subject=f'Статус реєстрації змінено: {event.title}',
            template_name='status_changed',
            context={
                'user': user, 'event': event, 'registration': registration,
                'old_status': old_status, 'new_status': new_status,
                'new_status_label': label,
            },
            trigger='status_change',
            registration_id=registration.id,
        )

    @staticmethod
    def send_course_request_notification(course_request):
        """Повідомити адмінів про новий CourseRequest (клієнт залишив запит).

        Отримувач -- SiteSettings.email (контактний email інституту). Якщо
        не заповнений -- шлемо на всіх User.is_admin=True. Якщо і таких
        немає -- пропускаємо з warning.
        """
        from app.models.site_settings import SiteSettings
        from app.models.user import User

        recipients = []
        settings = SiteSettings.get()
        if settings.email:
            recipients.append(settings.email.strip())
        else:
            admins = User.query.filter_by(is_admin=True, is_active=True).all()
            recipients = [u.email for u in admins if u.email]

        if not recipients:
            logger.warning(
                'No admin recipients configured for CourseRequest #%s notification',
                course_request.id,
            )
            return []

        course = course_request.course
        subject = f'Новий запит на курс: {course.title if course else course_request.course_id}'
        results = []
        for to in recipients:
            entry = EmailService.send_email(
                to=to,
                subject=subject,
                template_name='course_request_notification',
                context={
                    'request_obj': course_request,
                    'course': course,
                },
                trigger='course_request',
            )
            results.append(entry)
        return results

    @staticmethod
    def send_test_email(to):
        """Send test email synchronously so SMTP errors propagate to caller."""
        app = current_app._get_current_object()

        with app.app_context():
            smtp_cfg = _get_smtp_config(app)

        if not smtp_cfg['is_enabled']:
            log_entry = EmailLog(
                to_email=to,
                subject='IPRM: Тестовий лист',
                template_name='test',
                status='failed',
                error_message='Email sending is disabled in settings',
                trigger='test',
            )
            db.session.add(log_entry)
            db.session.commit()
            raise RuntimeError('Email sending is disabled in settings')

        if not smtp_cfg['server'] or not smtp_cfg['username']:
            raise RuntimeError('SMTP сервер або логін не налаштовані')

        if not smtp_cfg['has_password']:
            raise RuntimeError('SMTP пароль не налаштований')

        html_body = render_template('emails/test.html', to_email=to)
        plain_body = _html_to_plaintext(html_body)
        msg = Message(
            subject='IPRM: Тестовий лист',
            recipients=[to],
            html=html_body,
            body=plain_body,
            sender=smtp_cfg['sender'],
        )

        log_entry = EmailLog(
            to_email=to,
            subject='IPRM: Тестовий лист',
            template_name='test',
            status='pending',
            trigger='test',
            html_body=html_body,
        )
        db.session.add(log_entry)
        db.session.commit()

        try:
            _smtp_send(msg, smtp_cfg)
            log_entry.status = 'sent'
            log_entry.sent_at = datetime.now(timezone.utc)
            db.session.commit()
            logger.info('Test email sent to %s', to)
        except Exception as exc:
            log_entry.status = 'failed'
            log_entry.error_message = str(exc)[:500]
            db.session.commit()
            logger.exception('Failed to send test email to %s', to)
            raise
        return log_entry

    # ---- Queue maintenance ----

    @staticmethod
    def cleanup_stale_pending():
        """Mark emails stuck in 'pending' longer than STALE_PENDING_MINUTES as failed.

        Uses batch UPDATE for efficiency.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PENDING_MINUTES)
        count = EmailLog.query.filter(
            EmailLog.status == 'pending',
            EmailLog.created_at < cutoff,
        ).update({
            EmailLog.status: 'failed',
            EmailLog.error_message: f'Timeout: stuck in pending >{STALE_PENDING_MINUTES} min',
        }, synchronize_session=False)

        if count:
            db.session.commit()
            logger.info('Cleaned up %d stale pending emails', count)

        return count

    @staticmethod
    def retry_failed_emails():
        """Retry failed emails using saved html_body (no re-render needed).

        Eligible: transient errors, under max retries, last hour, not test.
        Skips if circuit breaker is open.
        """
        from app.models.email_settings import EmailSettings
        settings = EmailSettings.get()
        if not settings.is_enabled:
            return 0

        if EmailService._check_circuit_breaker():
            logger.warning('Circuit breaker open: skipping retry cycle')
            return 0

        smtp_cfg = _get_smtp_config(current_app._get_current_object())

        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        failed = EmailLog.query.filter(
            EmailLog.status == 'failed',
            EmailLog.retry_count < MAX_RETRIES,
            EmailLog.trigger != 'test',
            EmailLog.created_at >= cutoff,
            EmailLog.html_body.isnot(None),
        ).order_by(EmailLog.created_at.asc()).limit(10).all()

        retried = 0
        for entry in failed:
            if not entry.is_retryable:
                continue

            entry.retry_count += 1
            entry.status = 'pending'
            db.session.flush()

            try:
                plain_body = _html_to_plaintext(entry.html_body)
                msg = Message(
                    subject=entry.subject,
                    recipients=[entry.to_email],
                    html=entry.html_body,
                    body=plain_body,
                    sender=smtp_cfg['sender'],
                )
                _smtp_send(msg, smtp_cfg)
                entry.status = 'sent'
                entry.sent_at = datetime.now(timezone.utc)
                entry.error_message = None
                logger.info('Retry OK: id=%s to=%s (attempt %d)',
                            entry.id, entry.to_email, entry.retry_count)
                retried += 1
            except Exception as exc:
                entry.status = 'failed'
                entry.error_message = f'Retry {entry.retry_count} failed: {str(exc)[:400]}'
                logger.warning('Retry FAILED: id=%s to=%s (attempt %d): %s',
                               entry.id, entry.to_email, entry.retry_count, exc)
            finally:
                db.session.commit()

        if retried:
            logger.info('Retried %d/%d failed emails', retried, len(failed))

        return retried
