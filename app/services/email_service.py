"""
Email sending service with threaded delivery and audit logging.

Reads SMTP settings from EmailSettings model (DB) before each send.
Uses Flask-Mail for SMTP, threading.Thread for non-blocking sends,
and EmailLog model for audit trail.
"""
import logging
from datetime import datetime, timezone
from threading import Thread

from flask import current_app, render_template
from flask_mail import Message

from app.extensions import db, mail
from app.models.email_log import EmailLog

logger = logging.getLogger(__name__)


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

        # Завантажуємо налаштування з БД
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

        html_body = render_template(f'emails/{template_name}.html', **ctx)

        sender = app.config.get('MAIL_DEFAULT_SENDER')
        msg = Message(
            subject=subject,
            recipients=[to],
            html=html_body,
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
            # Перезавантажуємо налаштування для thread
            EmailService._load_settings(app)

            log_entry = db.session.get(EmailLog, log_id)
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
        return EmailService.send_email(
            to=to,
            subject='IPRM: Тестовий лист',
            template_name='test',
            context={'to_email': to},
            trigger='test',
        )
