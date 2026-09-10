"""Тема проведення: власна перебиває назву курсу, порожня -- успадковує."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance


def _pair(topic=None, course_title='Базовий курс'):
    course = Course(title=course_title, slug=f'top-{uuid4().hex[:6]}',
                    is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, topic=topic,
        start_date=datetime.now(timezone.utc) + timedelta(days=7),
        status='published',
    )
    db.session.add(inst)
    db.session.flush()
    return course, inst


def test_instance_without_topic_uses_course_title(db_session):
    _course, inst = _pair()
    assert inst.effective_title == 'Базовий курс'


def test_topic_overrides_course_title(db_session):
    course, inst = _pair(topic='PRP у практиці ортопеда')
    assert inst.effective_title == 'PRP у практиці ортопеда'
    assert course.title == 'Базовий курс'


def test_blank_topic_is_same_as_empty(db_session):
    _course, inst = _pair(topic='   ')
    assert inst.effective_title == 'Базовий курс'


def test_orphan_instance_has_no_title(db_session):
    """Проведення без курсу не вигадує назву -- рішення за викликачем."""
    inst = CourseInstance(status='draft')
    assert inst.effective_title is None


def test_topic_translation_used_for_that_language(db_session):
    _course, inst = _pair(topic='Тема українською')
    inst.set_translation('ru', 'topic', 'Тема по-русски')
    assert inst.effective_title_for('ru') == 'Тема по-русски'
    assert inst.effective_title_for('uk') == 'Тема українською'


def test_untranslated_topic_falls_back_to_ukrainian(db_session):
    _course, inst = _pair(topic='Тема українською')
    assert inst.effective_title_for('en') == 'Тема українською'


def test_without_topic_course_translation_wins(db_session):
    course, inst = _pair()
    course.set_translation('ru', 'title', 'Базовый курс')
    assert inst.effective_title_for('ru') == 'Базовый курс'
