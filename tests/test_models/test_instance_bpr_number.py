"""Реєстраційний номер заходу БПР на проведенні з успадкуванням від курсу.

Номер реєстру належить конкретному поданню, а курс -- лише загальна обгортка.
Тому проведення несе власне поле, а курсове лишається відкатом для дат, яким
номер ще не виписали.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance


@pytest.fixture
def course(app):
    row = Course(
        title='Курс плазмотерапії',
        slug=f'bpr-num-{uuid4().hex[:8]}',
        bpr_event_number='1028974',
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_instance_inherits_course_number(course):
    instance = CourseInstance(course_id=course.id)
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_bpr_event_number == '1028974'


def test_instance_own_number_wins(course):
    instance = CourseInstance(course_id=course.id, bpr_event_number='1031500')
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_bpr_event_number == '1031500'


def test_blank_own_number_falls_back_to_course(course):
    """Порожній рядок -- це "ще не виписали", а не "номера немає"."""
    instance = CourseInstance(course_id=course.id, bpr_event_number='   ')
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_bpr_event_number == '1028974'


def test_number_is_stripped(course):
    instance = CourseInstance(course_id=course.id, bpr_event_number=' 1031500 ')
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_bpr_event_number == '1031500'


def test_no_number_anywhere_is_empty(app):
    bare = Course(title='Курс без номера', slug=f'bpr-none-{uuid4().hex[:8]}')
    db.session.add(bare)
    db.session.flush()
    instance = CourseInstance(course_id=bare.id)
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_bpr_event_number == ''


def test_two_dates_of_one_course_carry_different_numbers(course):
    """Те, заради чого поле й заводиться: одна дата -- один номер реєстру."""
    first = CourseInstance(course_id=course.id, bpr_event_number='1031500')
    second = CourseInstance(course_id=course.id, bpr_event_number='1031501')
    db.session.add_all([first, second])
    db.session.commit()
    assert first.effective_bpr_event_number == '1031500'
    assert second.effective_bpr_event_number == '1031501'
