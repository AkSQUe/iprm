"""Рівень складності проведення: власний перебиває курсовий, порожній -- успадковує.

`distinct_difficulty_level` -- окрема властивість, а не умова в шаблоні:
правило «називаємо рівень лише там, де він відрізняється від курсового»
однакове для картки дати й для розкладу /courses, і мусить жити в одному
місці.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance


def _pair(course_level=2, instance_level=None):
    course = Course(title='К', slug=f'dl-{uuid4().hex[:6]}',
                    is_active=True, difficulty_level=course_level)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, difficulty_level=instance_level,
        start_date=datetime.now(timezone.utc) + timedelta(days=7),
        status='published',
    )
    db.session.add(inst)
    db.session.flush()
    return course, inst


def test_instance_inherits_course_level(db_session):
    _course, inst = _pair(course_level=2)
    assert inst.effective_difficulty_level == 2
    assert inst.difficulty_label == 'Рівень 2 — просунутий'


def test_instance_level_overrides_course_level(db_session):
    _course, inst = _pair(course_level=2, instance_level=3)
    assert inst.effective_difficulty_level == 3
    assert inst.difficulty_label == 'Рівень 3 — експертний'


def test_instance_without_any_level_has_no_label(db_session):
    _course, inst = _pair(course_level=None)
    assert inst.effective_difficulty_level is None
    assert inst.difficulty_label is None


def test_distinct_level_is_silent_while_the_date_follows_the_course(db_session):
    """Успадкований рівень -- не новина: його вже названо біля опису курсу."""
    _course, inst = _pair(course_level=2)
    assert inst.distinct_difficulty_level is None


def test_distinct_level_is_silent_when_the_override_repeats_the_course(db_session):
    """Заданий вручну, але той самий рівень -- теж не новина.

    Адмін має право продублювати курсовий рівень явно; читачеві сторінки
    від цього нічого не змінюється.
    """
    _course, inst = _pair(course_level=2, instance_level=2)
    assert inst.distinct_difficulty_level is None


def test_distinct_level_speaks_when_the_date_differs(db_session):
    _course, inst = _pair(course_level=2, instance_level=3)
    assert inst.distinct_difficulty_level == 3


def test_distinct_level_speaks_when_the_course_has_no_level_of_its_own(db_session):
    """Курс без рівня + дата з рівнем -- теж відмінність, і її треба назвати."""
    _course, inst = _pair(course_level=None, instance_level=1)
    assert inst.distinct_difficulty_level == 1


def test_level_outside_the_scale_is_refused_by_the_database(db_session):
    """Шкала 1..3 закрита в БД, а не лише у виборі адмінки."""
    _course, inst = _pair(course_level=2)
    inst.difficulty_level = 7
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()
