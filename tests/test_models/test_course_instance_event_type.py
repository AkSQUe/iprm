"""Тип проведення: власний перебиває курсовий, порожній -- успадковує."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance


def _pair(course_type='seminar', instance_type=None):
    course = Course(title='К', slug=f'ei-{uuid4().hex[:6]}',
                    is_active=True, event_type=course_type)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, event_type=instance_type,
        start_date=datetime.now(timezone.utc) + timedelta(days=7),
        status='published',
    )
    db.session.add(inst)
    db.session.flush()
    return course, inst


def test_instance_inherits_course_type(db_session):
    _course, inst = _pair(course_type='seminar')
    assert inst.effective_event_type == 'seminar'
    assert inst.event_type_label == 'Семінар'


def test_instance_type_overrides_course_type(db_session):
    _course, inst = _pair(course_type='seminar', instance_type='training')
    assert inst.effective_event_type == 'training'
    assert inst.event_type_label == 'Тренінг'


def test_instance_without_any_type_has_no_label(db_session):
    _course, inst = _pair(course_type=None)
    assert inst.effective_event_type is None
    assert inst.event_type_label is None


def test_deactivated_course_type_still_renders(db_session):
    """Курс зі старим типом мусить показувати «Курс», а не голий код."""
    course, inst = _pair(course_type='course')
    assert course.event_type_label == 'Курс'
    assert inst.event_type_label == 'Курс'
