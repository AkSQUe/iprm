"""Спільні utilities для admin blueprint: коміт + form helpers."""
from flask import current_app, flash
from sqlalchemy import func

from app.extensions import db


def try_commit(log_context='', error_msg='Помилка при збереженні'):
    """Виконати db.session.commit() з уніфікованою обробкою помилок.

    Повертає True при успіху. При помилці: rollback, логує через
    current_app.logger.exception, flash-ить error_msg і повертає False.
    """
    try:
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        current_app.logger.exception('DB commit failed: %s', log_context)
        flash(error_msg, 'error')
        return False


def populate_trainer_choices(form, empty_label='--- Default-тренер не обрано ---'):
    """Заповнити form.trainer_id.choices активними тренерами."""
    from app.models.trainer import Trainer
    trainers = (
        Trainer.query.filter_by(is_active=True)
        .order_by(Trainer.full_name)
        .all()
    )
    form.trainer_id.choices = [(0, empty_label)] + [
        (t.id, t.full_name) for t in trainers
    ]


def course_request_counts(status='pending', course_ids=None):
    """Агреговане {course_id: count} для CourseRequest з заданим статусом.

    Один запит замість N+1 через Course.pending_requests_count property.
    """
    from app.models.course_request import CourseRequest
    q = db.session.query(
        CourseRequest.course_id,
        func.count(CourseRequest.id),
    ).filter(CourseRequest.status == status)
    if course_ids is not None:
        q = q.filter(CourseRequest.course_id.in_(course_ids))
    return dict(q.group_by(CourseRequest.course_id).all())
