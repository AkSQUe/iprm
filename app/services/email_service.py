"""
Email sending service with threaded delivery and audit logging.

Reads SMTP settings from EmailSettings model (DB) before each send.
Uses Flask-Mail for SMTP, threading.Thread for non-blocking sends,
and EmailLog model for audit trail.
"""
import logging
import re
from datetime import datetime, timezone
from threading import Thread

from flask import current_app, render_template
from flask_mail import Message

from app.extensions import db, mail
from app.models.email_log import EmailLog

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r'<[^>]+>')
_WHITESPACE_RE = re.compile(r'\n\s*\n')


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
    def send_email(to, subject, template_name, context=None,
                   trigger=None, registration_id=None):
        """
        Render email template and send via SMTP in background thread.
        Reads SMTP config from DB before each send.

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
