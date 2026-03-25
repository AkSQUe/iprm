"""
APScheduler with SQLAlchemy jobstore for persistent scheduled jobs.

Runs a daily job scanning for upcoming events and sending reminders
to confirmed registrations.
"""
import logging
import os
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()
_initialized = False


def init_scheduler(app):
    """Initialize APScheduler with the app database for job persistence."""
    global _initialized
    if _initialized:
        return

    # Skip scheduler in reloader child process
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true' and app.debug:
        return

    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    jobstore = SQLAlchemyJobStore(url=db_uri)
    scheduler.configure(
        jobstores={'default': jobstore},
        job_defaults={
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 3600,
        },
    )

    scheduler._app = app

    scheduler.add_job(
        send_course_reminders,
        trigger=CronTrigger(hour=9, minute=0),
        id='daily_course_reminders',
        replace_existing=True,
        name='Нагадування перед курсами',
    )

    scheduler.start()
    _initialized = True
    logger.info('APScheduler started with SQLAlchemy jobstore')


def send_course_reminders():
    """Scan for upcoming events and send reminders."""
    app = scheduler._app
    with app.app_context():
        from sqlalchemy.orm import joinedload
        from app.models.event import Event
        from app.models.registration import EventRegistration
        from app.models.email_log import EmailLog
        from app.services.email_service import EmailService
        from app.extensions import db

        reminder_days = app.config.get('SCHEDULER_REMINDER_DAYS', [7, 3, 1])
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        for days in reminder_days:
            target_date = now + timedelta(days=days)
            window_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            window_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

            # Один запит: реєстрації з event та user (замість N+1)
            registrations = (
                EventRegistration.query
                .join(Event)
                .options(
                    joinedload(EventRegistration.event),
                    joinedload(EventRegistration.user),
                )
                .filter(
                    Event.start_date.between(window_start, window_end),
                    Event.status.in_(['published', 'active']),
                    EventRegistration.status.in_(['confirmed', 'completed']),
                )
                .all()
            )

            if not registrations:
                continue

            # Batch: одним запитом отримуємо всі вже відправлені reminders
            reg_ids = [r.id for r in registrations]
            already_sent_ids = set(
                row[0] for row in
                db.session.query(EmailLog.registration_id).filter(
                    EmailLog.registration_id.in_(reg_ids),
                    EmailLog.trigger == 'reminder',
                    EmailLog.created_at >= today_start,
                ).all()
            )

            for reg in registrations:
                if reg.id not in already_sent_ids:
                    try:
                        EmailService.send_course_reminder(reg, days)
                        logger.info(
                            'Reminder: reg=%d event=%d days=%d',
                            reg.id, reg.event_id, days,
                        )
                    except Exception:
                        logger.exception('Reminder failed: reg=%d', reg.id)

        logger.info('Course reminder job completed')
