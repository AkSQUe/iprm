"""SQLAlchemy listeners: при зміні Course або CourseInstance оповіщаємо
партнерські сайти через webhook.

Dispatch відбувається AFTER transaction commit (ніколи не всередині) --
щоб збій webhook не відкочував адмінські зміни. session.info збирає
pending-події під час транзакції, flush-ує їх у after_commit.

Legacy: раніше listener слухав Event. Тепер слухає Course (контент) і
CourseInstance (розклад). Payload все ще має поле `event_id` для
зворотної сумісності з партнерами -- у нього пишеться course.id.
"""
import logging

from sqlalchemy import event as sa_event

from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.services.webhook_dispatcher import dispatch_event_webhook

logger = logging.getLogger(__name__)

_PENDING_KEY = '_iprm_webhook_pending'


def _queue(session, course_id, course_slug, action):
    """Додати pending webhook (дедуплікує по ключу course_id+action)."""
    pending = session.info.setdefault(_PENDING_KEY, [])
    key = (course_id, action)
    # Дедуплікація: якщо за одну транзакцію кілька змін одного курсу --
    # відправимо webhook лише раз
    if any((p[0], p[2]) == key for p in pending):
        return
    pending.append((course_id, course_slug, action))


def _course_from_instance(instance):
    """Отримати Course з CourseInstance, навіть якщо relationship ще не завантажений."""
    if instance.course is not None:
        return instance.course
    from app.extensions import db
    return db.session.get(Course, instance.course_id)


def register_course_listeners(db) -> None:
    """Прив'язати after_{insert,update,delete} + after_commit hooks до
    Course і CourseInstance."""

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

    # Зміни розкладу трактуємо як updated курсу
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
        if not pending:
            return
        for course_id, course_slug, action in pending:
            try:
                dispatch_event_webhook(course_id, course_slug, action)
            except Exception:
                logger.exception(
                    'Webhook dispatch crashed unexpectedly for %s/%s',
                    action, course_slug,
                )

    @sa_event.listens_for(db.session, 'after_rollback')
    def _on_rollback(session):
        session.info.pop(_PENDING_KEY, None)
