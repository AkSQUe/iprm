"""
APScheduler with SQLAlchemy jobstore for persistent scheduled jobs.

Jobs:
- daily_course_reminders: daily at 09:00, sends reminders for upcoming events.
- email_queue_maintenance: every 5 min, cleans stale pending + retries failed.
- webhook_queue_worker: every minute, dispatches partner webhooks.

Multi-worker захист: gunicorn запускає N воркерів, у кожного власний
BackgroundScheduler. Без координації job виконається N разів -- це і є
причина дублювання нагадувань. PostgreSQL advisory lock гарантує що
тільки ОДИН воркер виконує job в даний момент.
"""
import hashlib
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()
_initialized = False


def _lock_id_for(job_name):
    """Стабільний int64 id для pg_try_advisory_lock на основі назви job-а."""
    digest = hashlib.sha256(job_name.encode('utf-8')).digest()
    # pg_try_advisory_lock приймає bigint (signed 64-bit) -- обрізаємо до 63 bits.
    return int.from_bytes(digest[:8], 'big', signed=False) & 0x7FFFFFFFFFFFFFFF


@contextmanager
def _job_lock(job_name):
    """Acquired pg_try_advisory_lock. Якщо зайнято -- yield False (skip)."""
    from app.extensions import db
    lock_id = _lock_id_for(job_name)
    got = db.session.execute(
        text('SELECT pg_try_advisory_lock(:id)'), {'id': lock_id}
    ).scalar()
    try:
        yield bool(got)
    finally:
        if got:
            db.session.execute(
                text('SELECT pg_advisory_unlock(:id)'), {'id': lock_id}
            )
            db.session.commit()


def init_scheduler(app):
    """Initialize APScheduler with the app database for job persistence."""
    global _initialized
    if _initialized:
        return

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

    scheduler.add_job(
        email_queue_maintenance,
        trigger=CronTrigger(minute='*/5'),
        id='email_queue_maintenance',
        replace_existing=True,
        name='Обслуговування черги email',
    )

    scheduler.add_job(
        process_webhook_queue,
        trigger=CronTrigger(minute='*'),  # every minute
        id='webhook_queue_worker',
        replace_existing=True,
        name='Відправка webhook-ів партнерам',
    )

    scheduler.start()
    _initialized = True
    logger.info('APScheduler started with SQLAlchemy jobstore')


def send_course_reminders():
    """Scan for upcoming events and send reminders.

    Multi-worker захист: pg_try_advisory_lock -- лише один воркер виконує.
    """
    app = scheduler._app
    with app.app_context():
        with _job_lock('daily_course_reminders') as got:
            if not got:
                logger.debug('reminders: another worker holds the lock, skipping')
                return
            _send_course_reminders_locked()


def _send_course_reminders_locked():
    """Тіло send_course_reminders виконується під pg-advisory-lock."""
    from sqlalchemy.orm import joinedload
    from app.models.course_instance import CourseInstance
    from app.models.registration import EventRegistration
    from app.models.email_log import EmailLog
    from app.models.email_settings import EmailSettings
    from app.services.email_service import EmailService
    from app.extensions import db

    settings = EmailSettings.get()
    reminder_days = settings.reminder_days_list

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    for days in reminder_days:
        target_date = now + timedelta(days=days)
        window_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        window_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        registrations = (
            EventRegistration.query
            .join(CourseInstance, EventRegistration.instance_id == CourseInstance.id)
            .options(
                joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
                joinedload(EventRegistration.user),
            )
            .filter(
                CourseInstance.start_date.between(window_start, window_end),
                CourseInstance.status.in_(['published', 'active']),
                EventRegistration.status.in_(['confirmed', 'completed']),
            )
            .all()
        )

        if not registrations:
            continue

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
                        'Reminder: reg=%d instance=%d days=%d',
                        reg.id, reg.instance_id, days,
                    )
                except Exception:
                    logger.exception('Reminder failed: reg=%d', reg.id)

    logger.info('Course reminder job completed')


def email_queue_maintenance():
    """Periodic job: clean stale pending emails and retry transient failures."""
    app = scheduler._app
    with app.app_context():
        with _job_lock('email_queue_maintenance') as got:
            if not got:
                logger.debug('email_queue: another worker holds the lock, skipping')
                return
            from app.services.email_service import EmailService

            stale_count = 0
            retry_count = 0

            try:
                stale_count = EmailService.cleanup_stale_pending()
            except Exception:
                logger.exception('cleanup_stale_pending failed')

            try:
                retry_count = EmailService.retry_failed_emails()
            except Exception:
                logger.exception('retry_failed_emails failed')

            if stale_count or retry_count:
                logger.info(
                    'Email maintenance: %d stale cleaned, %d retried',
                    stale_count, retry_count,
                )


def process_webhook_queue():
    """Periodic job: dispatch pending + retrying webhook deliveries."""
    app = scheduler._app
    with app.app_context():
        with _job_lock('webhook_queue_worker') as got:
            if not got:
                logger.debug('webhook_queue: another worker holds the lock, skipping')
                return
            from app.services.webhook_queue import process_queue
            try:
                stats = process_queue()
                if stats.get('processed'):
                    logger.info('Webhook queue: %s', stats)
            except Exception:
                logger.exception('process_webhook_queue failed')
