import pytest

from app.models.course import Course
from app.models.program_block import ProgramBlock
from app.models.trainer import Trainer


def test_course_creation(db_session):
    """Створення курсу з обов'язковими полями."""
    course = Course(title='Test Course', slug='test-course')
    db_session.add(course)
    db_session.flush()

    assert course.id is not None
    assert course.is_active is True
    assert course.is_featured is False


def test_course_event_type_label(db_session):
    """Computed property event_type_label."""
    course = Course(title='C', slug='c-type', event_type='course')
    assert course.event_type_label == 'Курс'


def test_course_trainer_relationship(db_session):
    """Зв'язок Course -> Trainer."""
    trainer = Trainer(full_name='Dr. Test', slug='dr-test')
    db_session.add(trainer)
    db_session.flush()

    course = Course(title='C', slug='c-trainer', trainer_id=trainer.id)
    db_session.add(course)
    db_session.flush()

    assert course.trainer.full_name == 'Dr. Test'


def test_course_program_blocks_cascade(db_session):
    """Каскадне видалення program_blocks при видаленні course."""
    course = Course(title='C', slug='c-cascade')
    db_session.add(course)
    db_session.flush()

    block = ProgramBlock(course_id=course.id, heading='Block 1', items=['item1'])
    db_session.add(block)
    db_session.flush()

    block_id = block.id
    db_session.delete(course)
    db_session.flush()

    assert db_session.get(ProgramBlock, block_id) is None


def test_course_unique_slug(db_session):
    """Slug має бути унікальним."""
    c1 = Course(title='C1', slug='same-slug')
    db_session.add(c1)
    db_session.flush()

    c2 = Course(title='C2', slug='same-slug')
    db_session.add(c2)
    with pytest.raises(Exception):
        db_session.flush()


def test_course_upcoming_instances_property(db_session):
    """Course.upcoming_instances повертає тільки активні майбутні проведення."""
    from datetime import datetime, timezone, timedelta
    from app.models.course_instance import CourseInstance

    course = Course(title='C', slug='c-upcoming', is_active=True)
    db_session.add(course)
    db_session.flush()

    now = datetime.now(timezone.utc)
    upcoming = CourseInstance(
        course_id=course.id,
        start_date=now + timedelta(days=5),
        status='published',
    )
    past = CourseInstance(
        course_id=course.id,
        start_date=now - timedelta(days=5),
        status='completed',
    )
    draft = CourseInstance(
        course_id=course.id,
        start_date=now + timedelta(days=10),
        status='draft',
    )
    db_session.add_all([upcoming, past, draft])
    db_session.flush()
    db_session.refresh(course)

    upcoming_ids = [i.id for i in course.upcoming_instances]
    assert upcoming.id in upcoming_ids
    assert past.id not in upcoming_ids
    assert draft.id not in upcoming_ids
