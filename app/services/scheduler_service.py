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
        send_certdata_reminders,
        trigger=CronTrigger(hour=9, minute=30),
        id='daily_certdata_reminders',
        replace_existing=True,
        name='Нагадування про дані для сертифіката',
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

    scheduler.add_job(
        cleanup_xlsx_uploads,
        trigger=CronTrigger(minute='*/15'),  # every 15 minutes
        id='xlsx_uploads_cleanup',
        replace_existing=True,
        name='Очищення тимчасових xlsx-вивантажень',
    )

    scheduler.add_job(
        automatic_database_backup,
        trigger=CronTrigger(hour=3, minute=0),  # daily at 3:00 AM
        id='automatic_database_backup',
        replace_existing=True,
        name='Автоматичне резервне копіювання БД',
    )

    scheduler.add_job(
        backup_cleanup,
        trigger=CronTrigger(hour=4, minute=0),  # daily at 4:00 AM
        id='backup_cleanup',
        replace_existing=True,
        name='Очищення старих резервних копій',
    )

    scheduler.add_job(
        purge_soft_deleted,
        trigger=CronTrigger(hour=4, minute=30),  # daily at 4:30 AM
        id='soft_deleted_purge',
        replace_existing=True,
        name='Остаточне видалення м\'яко видалених записів',
    )

    scheduler.add_job(
        reconcile_material_reservations,
        trigger=CronTrigger(minute='*/30'),  # every 30 minutes
        id='material_reservations_reconcile',
        replace_existing=True,
        name='Звірка резервувань матеріалів MM Medic',
    )

    scheduler.add_job(
        mature_referral_rewards_job,
        trigger=CronTrigger(hour=8, minute=0),  # daily at 8:00 AM
        id='referral_rewards_maturity',
        replace_existing=True,
        name='Дозрівання реферальних балів',
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


def send_certdata_reminders():
    """Нагадати учасникам близьких заходів заповнити МОЗ-анкету.

    Multi-worker захист: pg_try_advisory_lock -- лише один воркер виконує.
    """
    app = scheduler._app
    with app.app_context():
        with _job_lock('daily_certdata_reminders') as got:
            if not got:
                logger.debug('certdata: another worker holds the lock, skipping')
                return
            _send_certdata_reminders_locked()


def _send_certdata_reminders_locked():
    """Тіло send_certdata_reminders під pg-advisory-lock.

    Вибірка: активні (не cancelled) реєстрації на published/active
    проведення, до старту яких лишилося <= N днів
    (SiteSettings.certdata_reminder_days; 0 -- вимкнено), лист ще не
    надсилався (certdata_reminder_sent_at IS NULL), а МОЗ-анкета
    користувача неповна. Один лист на реєстрацію.
    """
    from sqlalchemy.orm import joinedload
    from app.extensions import db
    from app.models.course_instance import CourseInstance
    from app.models.registration import EventRegistration
    from app.models.site_settings import SiteSettings
    from app.models.user import User
    from app.services.email_service import EmailService

    days = SiteSettings.get().certdata_reminder_days or 0
    if days <= 0:
        logger.debug('certdata reminders disabled (days=0)')
        return

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=days)

    registrations = (
        EventRegistration.query
        .join(CourseInstance, EventRegistration.instance_id == CourseInstance.id)
        .options(
            joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
            joinedload(EventRegistration.user).joinedload(User.medical_profile),
        )
        .filter(
            CourseInstance.start_date.between(now, window_end),
            CourseInstance.status.in_(['published', 'active']),
            EventRegistration.status != 'cancelled',
            EventRegistration.certdata_reminder_sent_at.is_(None),
        )
        .all()
    )

    sent = 0
    for reg in registrations:
        user = reg.user
        if user is None or not user.email:
            continue
        profile = user.medical_profile
        if profile is not None and profile.is_complete:
            # Анкета вже заповнена -- позначаємо, щоб не сканувати повторно.
            reg.certdata_reminder_sent_at = now
            continue
        try:
            EmailService.send_certdata_reminder(reg)
            reg.certdata_reminder_sent_at = now
            sent += 1
            logger.info(
                'Certdata reminder: reg=%d instance=%d user=%d',
                reg.id, reg.instance_id, reg.user_id,
            )
        except Exception:
            logger.exception('Certdata reminder failed: reg=%d', reg.id)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Certdata reminder job: failed to persist sent flags')
    logger.info('Certdata reminder job completed: sent=%d of %d candidates',
                sent, len(registrations))


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

            bounce_count = 0
            try:
                from app.services.bounce_service import poll_bounces
                bounce_count = poll_bounces()  # no-op, якщо вимкнено в налаштуваннях
            except Exception:
                logger.exception('poll_bounces failed')

            if stale_count or retry_count or bounce_count:
                logger.info(
                    'Email maintenance: %d stale cleaned, %d retried, %d bounces suppressed',
                    stale_count, retry_count, bounce_count,
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


def cleanup_xlsx_uploads():
    """Periodic job: delete admin xlsx-import temp files older than 30 min."""
    app = scheduler._app
    with app.app_context():
        with _job_lock('xlsx_uploads_cleanup') as got:
            if not got:
                logger.debug('xlsx_cleanup: another worker holds the lock, skipping')
                return
            from app.services.xlsx_io import cleanup_stale_xlsx_uploads
            try:
                cleanup_stale_xlsx_uploads(max_age_minutes=30)
            except Exception:
                logger.exception('cleanup_xlsx_uploads failed')


def purge_soft_deleted():
    """Periodic job: остаточно прибрати м'яко видалені рядки після витримки.

    М'яке видалення існує заради відкату (тост "Повернути"), а не заради
    архіву: через SOFT_DELETE_RETENTION_DAYS рядок і файли зникають назавжди.
    """
    app = scheduler._app
    with app.app_context():
        with _job_lock('soft_deleted_purge') as got:
            if not got:
                logger.debug('purge: another worker holds the lock, skipping')
                return
            try:
                from app.services.soft_delete_purge import purge_expired
                stats = purge_expired()
                if any(stats.values()):
                    logger.info('purge_soft_deleted: %s', stats)
            except Exception:
                logger.exception('purge_soft_deleted failed')


def reconcile_material_reservations():
    """Periodic job: sync stale RESERVED material reservations with MM Medic and
    prune old prefill temp files."""
    app = scheduler._app
    with app.app_context():
        with _job_lock('material_reservations_reconcile') as got:
            if not got:
                logger.debug('material reconcile: another worker holds the lock, skipping')
                return
            try:
                from app.services.material_reservation_service import (
                    reconcile_stale, send_pending_actuals_reminders,
                )
                reminded = send_pending_actuals_reminders()
                if reminded:
                    logger.info('Material actuals reminders sent: %d', reminded)
                updated = reconcile_stale()
                if updated:
                    logger.info('Material reservations reconciled: %d updated', updated)
            except Exception:
                logger.exception('reconcile_material_reservations failed')
            _prune_material_prefill()


def _prune_material_prefill(max_age_minutes=60):
    """Remove abandoned material-prefill temp JSON files."""
    from pathlib import Path
    from flask import current_app
    target = Path(current_app.instance_path) / 'material_prefill'
    if not target.is_dir():
        return
    cutoff = datetime.now().timestamp() - max_age_minutes * 60
    for p in target.glob('*.json'):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            logger.exception('Failed to prune prefill file %s', p)


def mature_referral_rewards_job():
    """Щоденно активувати дозрілі pending-нарахування реферальних балів."""
    app = scheduler._app
    with app.app_context():
        with _job_lock('referral_rewards_maturity') as got:
            if not got:
                logger.debug('referral maturity: another worker holds the lock, skipping')
                return
            from app.services import referral_service
            try:
                referral_service.mature_referral_rewards()
                # Звірка денормалізованих балансів (самозцілення дрейфу).
                referral_service.reconcile_balances()
            except Exception:
                logger.exception('Referral maturity job failed')


def automatic_database_backup():
    """Daily automatic full database backup with email notification on failure."""
    app = scheduler._app
    with app.app_context():
        with _job_lock('automatic_database_backup') as got:
            if not got:
                logger.debug('auto_backup: another worker holds the lock, skipping')
                return
            from app.services.backup_service import BackupService, BackupError
            try:
                backup = BackupService.create_backup(
                    backup_type='full',
                    description='Автоматична щоденна копія',
                )
                logger.info(
                    'Auto backup created: %s (%s, %.1fs)',
                    backup.filename, backup.file_size_display, backup.duration_seconds or 0,
                )
            except BackupError as exc:
                logger.exception('Automatic backup failed: %s', exc)
                _notify_backup_failure(str(exc))
            except Exception as exc:
                logger.exception('Automatic backup failed unexpectedly')
                _notify_backup_failure(str(exc))


def backup_cleanup():
    """Daily cleanup of old backups according to retention policy."""
    app = scheduler._app
    with app.app_context():
        with _job_lock('backup_cleanup') as got:
            if not got:
                logger.debug('backup_cleanup: another worker holds the lock, skipping')
                return
            from app.services.backup_service import BackupService
            try:
                result = BackupService.cleanup_old_backups()
                if result.get('deleted'):
                    logger.info('Backup cleanup: deleted %d old backups', result['deleted'])
            except Exception:
                logger.exception('Backup cleanup failed')


def _notify_backup_failure(error_message):
    """Send email notification to admins about backup failure."""
    try:
        from app.models.email_settings import EmailSettings
        from app.models.site_settings import SiteSettings
        from app.services.email_service import EmailService
        from flask import url_for

        email_settings = EmailSettings.get()
        if not email_settings.smtp_server:
            return

        site_settings = SiteSettings.get()
        manager_emails = site_settings.event_manager_emails or []
        if not manager_emails:
            return

        app = scheduler._app
        with app.app_context():
            try:
                admin_url = url_for('admin.backups', _external=True)
            except Exception:
                admin_url = '/admin/backups'

        subject = '[ІПРМ] Помилка автоматичного резервного копіювання'
        context = {
            'error_message': error_message,
            'admin_url': admin_url,
        }

        for email in manager_emails:
            try:
                EmailService.send_email(
                    to=email,
                    subject=subject,
                    template_name='backup_failure',
                    context=context,
                    trigger='backup_failure',
                )
            except Exception:
                logger.exception('Failed to send backup failure notification to %s', email)
    except Exception:
        logger.exception('Failed to send backup failure notification')
