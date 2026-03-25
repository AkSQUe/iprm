"""
Email sending service with threaded delivery, retry logic, and audit logging.

Protection system:
- Stale pending cleanup: emails stuck >5 min in "pending" are marked failed.
- Retry with backoff: transient SMTP failures retried up to 3 times.
- Permanent failure detection: auth errors, bad addresses are never retried.
- Deduplication: same trigger+registration within 60s window is skipped.
- Circuit breaker: if >5 failures in last 10 min, new sends are paused.
- Test emails are always synchronous and never retried.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from threading import Thread

from flask import current_app, render_template
from flask_mail import Message

from app.extensions import db, mail
from app.models.email_log import EmailLog, MAX_RETRIES, STALE_PENDING_MINUTES

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r'<[^>]+>')
_WHITESPACE_RE = re.compile(r'\n\s*\n')

# Dedup window: skip if identical email was created within this many seconds.
DEDUP_WINDOW_SECONDS = 60

# Circuit breaker: pause if more than this many failures in the window.
CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_WINDOW_MINUTES = 10


def _html_to_plaintext(html):
    """Minimal HTML-to-text conversion for email plain text fallback."""
    text = html.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
    text = _HTML_TAG_RE.sub('', text)
    text = _WHITESPACE_RE.sub('\n\n', text)
    return text.strip()


class EmailService:

    @staticmethod
    def _load_settings(app):
        """Load SMTP settings from DB and apply to Flask-Mail config."""
        from app.models.email_settings import EmailSettings
        with app.app_context():
            settings = EmailSettings.get()
            settings.apply_to_app(app)
            return settings

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
        """
        app = current_app._get_current_object()
        ctx = context or {}

        settings = EmailService._load_settings(app)

        if not settings.is_enabled:
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

        # Dedup guard
        if EmailService._check_duplicate(to, trigger, registration_id):
            logger.info('Dedup: skipping %s -> %s (trigger=%s reg=%s)',
                        template_name, to, trigger, registration_id)
            return None

        # Circuit breaker
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

        log_entry = EmailLog(
            to_email=to,
            subject=subject,
            template_name=template_name,
            status='pending',
            trigger=trigger,
            registration_id=registration_id,
        )
        db.session.add(log_entry)
        db.session.commit()

        try:
            html_body = render_template(f'emails/{template_name}.html', **ctx)
        except Exception as exc:
            log_entry.status = 'failed'
            log_entry.error_message = f'Template render error: {str(exc)[:400]}'
            db.session.commit()
            logger.exception('Failed to render email template %s', template_name)
            return log_entry

        sender = app.config.get('MAIL_DEFAULT_SENDER')
        plain_body = _html_to_plaintext(html_body)
        msg = Message(
            subject=subject,
            recipients=[to],
            html=html_body,
            body=plain_body,
            sender=sender,
        )

        thread = Thread(
            target=EmailService._send_in_thread,
            args=(app, msg, log_entry.id),
        )
        thread.daemon = True
        thread.start()

        return log_entry

    @staticmethod
    def _send_in_thread(app, msg, log_id):
        """Execute SMTP send inside app context, update EmailLog."""
        with app.app_context():
            EmailService._load_settings(app)

            log_entry = db.session.get(EmailLog, log_id)
            if not log_entry:
                logger.error('EmailLog %s not found in thread', log_id)
                return
            try:
                mail.send(msg)
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
    def send_test_email(to):
        """Send test email synchronously so SMTP errors propagate to caller."""
        app = current_app._get_current_object()
        settings = EmailService._load_settings(app)

        if not settings.is_enabled:
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

        if not settings.smtp_server or not settings.smtp_username:
            raise RuntimeError('SMTP сервер або логін не налаштовані')

        if not settings.has_password:
            raise RuntimeError('SMTP пароль не налаштований')

        html_body = render_template('emails/test.html', to_email=to)
        plain_body = _html_to_plaintext(html_body)
        sender = app.config.get('MAIL_DEFAULT_SENDER')
        msg = Message(
            subject='IPRM: Тестовий лист',
            recipients=[to],
            html=html_body,
            body=plain_body,
            sender=sender,
        )

        log_entry = EmailLog(
            to_email=to,
            subject='IPRM: Тестовий лист',
            template_name='test',
            status='pending',
            trigger='test',
        )
        db.session.add(log_entry)
        db.session.commit()

        try:
            mail.send(msg)
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
    def cleanup_stale_pending(app):
        """Mark emails stuck in 'pending' longer than STALE_PENDING_MINUTES as failed."""
        with app.app_context():
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PENDING_MINUTES)
            stale = EmailLog.query.filter(
                EmailLog.status == 'pending',
                EmailLog.created_at < cutoff,
            ).all()

            for entry in stale:
                entry.status = 'failed'
                entry.error_message = (
                    f'Timeout: stuck in pending for >{STALE_PENDING_MINUTES} min '
                    f'(previous error: {entry.error_message or "none"})'
                )
                logger.warning('Stale pending email marked failed: id=%s to=%s',
                               entry.id, entry.to_email)

            if stale:
                db.session.commit()
                logger.info('Cleaned up %d stale pending emails', len(stale))

            return len(stale)

    @staticmethod
    def retry_failed_emails(app):
        """Retry failed emails that are eligible (transient errors, under max retries)."""
        with app.app_context():
            from app.models.email_settings import EmailSettings
            settings = EmailSettings.get()
            if not settings.is_enabled:
                return 0

            # Check circuit breaker before retrying
            cutoff_cb = datetime.now(timezone.utc) - timedelta(minutes=CIRCUIT_BREAKER_WINDOW_MINUTES)
            recent_failures = EmailLog.query.filter(
                EmailLog.status == 'failed',
                EmailLog.created_at >= cutoff_cb,
                EmailLog.trigger != 'test',
            ).count()
            if recent_failures >= CIRCUIT_BREAKER_THRESHOLD:
                logger.warning('Circuit breaker open: skipping retry cycle')
                return 0

            settings.apply_to_app(app)

            # Only retry emails failed in the last hour (not ancient ones)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            failed = EmailLog.query.filter(
                EmailLog.status == 'failed',
                EmailLog.retry_count < MAX_RETRIES,
                EmailLog.trigger != 'test',
                EmailLog.created_at >= cutoff,
            ).order_by(EmailLog.created_at.asc()).limit(10).all()

            retried = 0
            for entry in failed:
                if not entry.is_retryable:
                    continue

                entry.retry_count += 1
                entry.status = 'pending'
                entry.error_message = (
                    f'Retry {entry.retry_count}/{MAX_RETRIES}: {entry.error_message or ""}'
                )
                db.session.commit()

                try:
                    sender = app.config.get('MAIL_DEFAULT_SENDER')
                    html_body = render_template(
                        f'emails/{entry.template_name}.html',
                        to_email=entry.to_email,
                    )
                    plain_body = _html_to_plaintext(html_body)
                    msg = Message(
                        subject=entry.subject,
                        recipients=[entry.to_email],
                        html=html_body,
                        body=plain_body,
                        sender=sender,
                    )
                    mail.send(msg)
                    entry.status = 'sent'
                    entry.sent_at = datetime.now(timezone.utc)
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
