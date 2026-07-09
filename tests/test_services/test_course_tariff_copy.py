"""Копіювання шаблонних тарифів курсу в проведення (кнопка "Взяти з курсу").

Регресія: лічильник на кнопці показував усі шаблони курсу, а копіювались
лише ті, що пасують формату проведення -> для офлайн-проведення з 4 шаблонів
(2 онлайн + 2 офлайн/будь-який) переносилось 2. Тепер лічильник
(instance.copyable_course_tariffs) і копіювання -- одне джерело істини.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_tariff import CourseTariff
from app.services import course_service


def _course_with_four_templates():
    course = Course(title='PRP', slug='prp-tariff-copy', is_active=True, base_price=0)
    db.session.add(course)
    db.session.flush()
    templates = [
        CourseTariff(course_id=course.id, name='Онлайн', price=1500,
                     event_format='online', sort_order=1, is_active=True),
        CourseTariff(course_id=course.id, name='Онлайн+', price=2500,
                     event_format='online', sort_order=2, is_active=True),
        CourseTariff(course_id=course.id, name='Практикум', price=7500,
                     event_format='offline', sort_order=3, is_active=True),
        CourseTariff(course_id=course.id, name='Практикум з менторством', price=12000,
                     event_format=None, sort_order=4, is_active=True),
    ]
    db.session.add_all(templates)
    db.session.flush()
    return course


def _instance(course, event_format):
    inst = CourseInstance(
        course_id=course.id,
        start_date=datetime.now(timezone.utc) + timedelta(days=7),
        event_format=event_format,
        status='published',
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def test_offline_instance_copies_only_matching_tariffs():
    course = _course_with_four_templates()
    inst = _instance(course, 'offline')

    # Онлайн-шаблони не пасують офлайн-проведенню -> лишається офлайн + NULL.
    assert len(inst.copyable_course_tariffs) == 2
    copied = course_service.copy_course_tariffs_to_instance(inst)
    db.session.flush()
    assert copied == 2
    assert len(inst.active_tariffs) == 2
    names = {t.name for t in inst.active_tariffs}
    assert names == {'Практикум', 'Практикум з менторством'}


def test_online_instance_copies_online_and_any():
    course = _course_with_four_templates()
    inst = _instance(course, 'online')

    assert len(inst.copyable_course_tariffs) == 3  # 2 онлайн + NULL
    copied = course_service.copy_course_tariffs_to_instance(inst)
    db.session.flush()
    assert copied == 3


def test_hybrid_instance_copies_all_active():
    course = _course_with_four_templates()
    inst = _instance(course, 'hybrid')

    assert len(inst.copyable_course_tariffs) == 4
    copied = course_service.copy_course_tariffs_to_instance(inst)
    db.session.flush()
    assert copied == 4


def test_counter_matches_copied_count():
    """Лічильник кнопки і фактичне копіювання завжди збігаються."""
    course = _course_with_four_templates()
    for fmt in ('online', 'offline', 'hybrid'):
        inst = _instance(course, fmt)
        expected = len(inst.copyable_course_tariffs)
        copied = course_service.copy_course_tariffs_to_instance(inst)
        db.session.flush()
        assert copied == expected


def test_inactive_templates_excluded():
    course = _course_with_four_templates()
    # Деактивуємо офлайн-шаблон -> офлайн-проведення отримає лише NULL-тариф.
    offline_t = CourseTariff.query.filter_by(course_id=course.id, name='Практикум').first()
    offline_t.is_active = False
    db.session.flush()
    inst = _instance(course, 'offline')
    assert len(inst.copyable_course_tariffs) == 1
    copied = course_service.copy_course_tariffs_to_instance(inst)
    db.session.flush()
    assert copied == 1
