"""SQLAlchemy listeners: при зміні Course або CourseInstance ставимо
рядок у чергу WebhookDelivery.

Після COMMIT `session` викликаємо `webhook_queue.enqueue(...)` для кожного
зібраного за час транзакції сповіщення. Реальна доставка -- scheduler job
`process_webhook_queue` (періодично), з retry/backoff/circuit breaker.

Переваги queue-based підходу:
    * При crash додатку під час HTTP POST не губимо подію;
    * Адмін бачить історію в таблиці webhook_deliveries;
    * Multiple workers можуть спокійно обробляти чергу;
    * Ретраї прозорі (не треба тримати thread у памяті).
"""
import logging

from flask import has_app_context
from sqlalchemy import event as sa_event

from app.models.course import Course
from app.models.course_instance import CourseInstance

logger = logging.getLogger(__name__)

_PENDING_KEY = '_iprm_webhook_pending'
_PENDING_SEEN_KEY = '_iprm_webhook_seen_keys'


def _session_of(target, fallback_session):
    """Повертає session, до якої прикріплений target, з fallback на default."""
    from app.extensions import db
    return db.session.object_session(target) or fallback_session


def _queue(session, course_id, course_slug, action):
    """Додати pending webhook у session-scoped queue. Дедуплікує O(1) через set."""
    pending = session.info.setdefault(_PENDING_KEY, [])
    seen = session.info.setdefault(_PENDING_SEEN_KEY, set())
    key = (course_id, action)
    if key in seen:
        return
    seen.add(key)
    pending.append((course_id, course_slug, action))


def _course_from_instance(instance):
    """Отримати Course з CourseInstance, навіть якщо relationship ще не завантажений."""
    if instance.course is not None:
        return instance.course
    from app.extensions import db
    return db.session.get(Course, instance.course_id)


def register_course_listeners(db) -> None:
    """Прив'язати after_{insert,update,delete} + after_commit hooks до
    Course та CourseInstance."""

    @sa_event.listens_for(Course, 'after_insert')
    def _on_course_insert(mapper, connection, target):
        _queue(_session_of(target, db.session), target.id, target.slug, 'created')

    @sa_event.listens_for(Course, 'after_update')
    def _on_course_update(mapper, connection, target):
        _queue(_session_of(target, db.session), target.id, target.slug, 'updated')

    @sa_event.listens_for(Course, 'after_delete')
    def _on_course_delete(mapper, connection, target):
        _queue(_session_of(target, db.session), target.id, target.slug, 'deleted')

    @sa_event.listens_for(CourseInstance, 'after_insert')
    def _on_instance_insert(mapper, connection, target):
        course = _course_from_instance(target)
        if course:
            _queue(_session_of(target, db.session), course.id, course.slug, 'updated')

    @sa_event.listens_for(CourseInstance, 'after_update')
    def _on_instance_update(mapper, connection, target):
        course = _course_from_instance(target)
        if course:
            _queue(_session_of(target, db.session), course.id, course.slug, 'updated')

    @sa_event.listens_for(CourseInstance, 'after_delete')
    def _on_instance_delete(mapper, connection, target):
        course = _course_from_instance(target)
        if course:
            _queue(_session_of(target, db.session), course.id, course.slug, 'updated')

    @sa_event.listens_for(db.session, 'after_commit')
    def _on_commit(session):
        pending = session.info.pop(_PENDING_KEY, None)
        session.info.pop(_PENDING_SEEN_KEY, None)
        if not pending:
            return
        if not has_app_context():
            # CLI/scheduler випадок -- ми вже поза request context. Enqueue
            # не працює без app context (SiteSettings.get() потребує БД).
            # У цьому випадку події губляться, але scheduler process_queue
            # все одно не зможе нічого зробити без зовнішнього тригера.
            logger.warning(
                'commit without app context -- dropping %d pending webhook(s)',
                len(pending),
            )
            return
        # Enqueue у ТІЙ САМІЙ сесії/транзакції не можна -- ми вже після commit.
        # Відкриваємо нову міні-транзакцію для кожного enqueue у тій самій
        # сесії (db.session).
        from app.services.webhook_queue import enqueue
        for course_id, course_slug, action in pending:
            try:
                enqueue(course_id, course_slug, action)
            except Exception:
                logger.exception(
                    'Failed to enqueue webhook course=%s action=%s',
                    course_slug, action,
                )

    @sa_event.listens_for(db.session, 'after_rollback')
    def _on_rollback(session):
        pending = session.info.pop(_PENDING_KEY, None)
        session.info.pop(_PENDING_SEEN_KEY, None)
        if pending:
            logger.warning(
                'Transaction rolled back -- dropped %d pending webhook(s): %s',
                len(pending),
                [(slug, action) for _, slug, action in pending],
            )
