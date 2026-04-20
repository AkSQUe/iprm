from datetime import datetime, timezone, timedelta

import pytest

from app.models.course import Course
from app.models.course_instance import CourseInstance


@pytest.fixture
def parent_course(db_session):
    course = Course(title='Parent', slug='ci-parent', base_price=1000, cpd_points=10, max_participants=30)
    db_session.add(course)
    db_session.flush()
    return course


def test_instance_creation(db_session, parent_course):
    """Створення проведення з обов'язковим course_id."""
    inst = CourseInstance(
        course_id=parent_course.id,
        start_date=datetime.now(timezone.utc) + timedelta(days=3),
        status='published',
        event_format='online',
    )
    db_session.add(inst)
    db_session.flush()

    assert inst.id is not None
    assert inst.status == 'published'


def test_instance_status_label(db_session, parent_course):
    inst = CourseInstance(course_id=parent_course.id, status='active')
    assert inst.status_label == 'Активний'


def test_instance_format_label(db_session, parent_course):
    inst = CourseInstance(course_id=parent_course.id, event_format='online')
    assert inst.format_label == 'Онлайн'


def test_instance_effective_price_falls_back_to_course(db_session, parent_course):
    """Якщо інстанс не має власної ціни -- використовуємо Course.base_price."""
    inst = CourseInstance(course_id=parent_course.id, price=None)
    db_session.add(inst)
    db_session.flush()
    db_session.refresh(inst)
    assert inst.effective_price == parent_course.base_price


def test_instance_effective_price_override(db_session, parent_course):
    """Власна ціна інстансу перекриває Course.base_price."""
    inst = CourseInstance(course_id=parent_course.id, price=2500)
    db_session.add(inst)
    db_session.flush()
    db_session.refresh(inst)
    assert inst.effective_price == 2500


def test_instance_can_transition_to_valid(db_session, parent_course):
    inst = CourseInstance(course_id=parent_course.id, status='draft')
    assert inst.can_transition_to('published') is True
    assert inst.can_transition_to('active') is True
    assert inst.can_transition_to('cancelled') is True


def test_instance_can_transition_to_invalid(db_session, parent_course):
    inst = CourseInstance(course_id=parent_course.id, status='completed')
    # completed -- фінальний стан
    assert inst.can_transition_to('draft') is False
    assert inst.can_transition_to('published') is False


def test_instance_is_registration_open(db_session, parent_course):
    """Відкрита реєстрація на published/active коли є місця."""
    inst = CourseInstance(
        course_id=parent_course.id,
        status='published',
        max_participants=10,
    )
    db_session.add(inst)
    db_session.flush()
    db_session.refresh(inst)
    assert inst.is_registration_open is True

    inst.status = 'draft'
    assert inst.is_registration_open is False
