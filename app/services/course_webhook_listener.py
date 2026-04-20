"""SQLAlchemy listeners: при зміні Course або CourseInstance оповіщаємо
партнерські сайти через webhook.

Dispatch відбувається AFTER transaction commit (ніколи не всередині) --
щоб збій webhook не відкочував адмінські зміни. session.info збирає
pending-події під час транзакції, flush-ує їх у after_commit у фоновому
треді (щоб таймаути HTTP не блокували HTTP-відповідь адміну).

Legacy: раніше listener слухав Event. Тепер слухає Course (контент) і
CourseInstance (розклад). Payload все ще має поле `event_id` для
зворотної сумісності з партнерами -- у нього пишеться course.id.
"""
import logging
import threading

from flask import current_app, has_app_context
from sqlalchemy import event as sa_event

from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.services.webhook_dispatcher import dispatch_event_webhook

logger = logging.getLogger(__name__)

_PENDING_KEY = '_iprm_webhook_pending'
_PENDING_SEEN_KEY = '_iprm_webhook_seen_keys'


def _queue(session, course_id, course_slug, action):
    """Додати pending webhook; дедуплікує за (course_id, action) через set -- O(1)."""
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


def _dispatch_all(pending, app):
    """Послідовно відправити усі pending webhooks у власному app context.

    Виконується у фоновому треді. Помилки логуються, не кидаються.
    """
    with app.app_context():
        for course_id, course_slug, action in pending:
            try:
                dispatch_event_webhook(course_id, course_slug, action)
            except Exception:
                logger.exception(
                    'Webhook dispatch crashed for %s/%s (course=%s)',
                    action, course_slug, course_id,
                )


def register_course_listeners(db) -> None:
    """Прив'язати after_{insert,update,delete} + after_commit hooks до
    Course та CourseInstance."""

    @sa_event.listens_for(Course, 'after_insert')
    def _on_course_insert(mapper, connection, target):
        session = db.session.object_session(target) or db.session
        _queue(session, target.id, target.slug, 'created')

    @sa_event.listens_for(Course, 'after_update')
    def _on_course_update(mapper, connection, target):
        session = db.session.object_session(target) or db.session
        _queue(session, target.id, target.slug, 'updated')

    @sa_event.listens_for(Course, 'after_delete')
    def _on_course_delete(mapper, connection, target):
        session = db.session.object_session(target) or db.session
        _queue(session, target.id, target.slug, 'deleted')

    @sa_event.listens_for(CourseInstance, 'after_insert')
    def _on_instance_insert(mapper, connection, target):
        session = db.session.object_session(target) or db.session
        course = _course_from_instance(target)
        if course:
            _queue(session, course.id, course.slug, 'updated')

    @sa_event.listens_for(CourseInstance, 'after_update')
    def _on_instance_update(mapper, connection, target):
        session = db.session.object_session(target) or db.session
        course = _course_from_instance(target)
        if course:
            _queue(session, course.id, course.slug, 'updated')

    @sa_event.listens_for(CourseInstance, 'after_delete')
    def _on_instance_delete(mapper, connection, target):
        session = db.session.object_session(target) or db.session
        course = _course_from_instance(target)
        if course:
            _queue(session, course.id, course.slug, 'updated')

    @sa_event.listens_for(db.session, 'after_commit')
    def _on_commit(session):
        pending = session.info.pop(_PENDING_KEY, None)
        session.info.pop(_PENDING_SEEN_KEY, None)
        if not pending:
            return
        # Передаємо snapshot у фоновий тред разом із app proxy; inside
        # thread викличемо app.app_context() щоб логер та dispatcher
        # мали контекст.
        app = current_app._get_current_object() if has_app_context() else None
        if app is None:
            # Не в запиті (scheduler, CLI) -- dispatch синхронно.
            _dispatch_all(pending, current_app._get_current_object())
            return
        threading.Thread(
            target=_dispatch_all,
            args=(pending, app),
            daemon=True,
            name='webhook-dispatch',
        ).start()

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
