"""Розклад (публічний /courses/): рівень складності конкретного проведення.

Дати одного курсу можуть мати різний рівень підготовки, і саме в розкладі
відвідувач порівнює дати між собою. Тег ставимо лише там, де рівень
відрізняється від курсового: інакше той самий підпис повторювався б у
кожному рядку курсу й нічого не розрізняв.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance

SLUG_PREFIX = 'sched-level-'


@pytest.fixture(autouse=True)
def clean(app):
    """Прибрати за собою курси: тестова БД спільна на всю сесію, а розклад
    на /courses показує всі майбутні проведення."""
    def _wipe():
        Course.query.filter(Course.slug.like(f'{SLUG_PREFIX}%')).delete(
            synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


def _pair(title, course_level=2, instance_level=None):
    course = Course(title=title, slug=f'{SLUG_PREFIX}{uuid4().hex[:6]}',
                    is_active=True, difficulty_level=course_level)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, difficulty_level=instance_level,
        status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=3),
    )
    db.session.add(inst)
    db.session.flush()
    return course, inst


def _schedule_item(client, title):
    """Розмітка одного рядка розкладу -- саме нашого проведення.

    Вкладка «Список» показує заходи всіх курсів; шукати тег по всій панелі
    означало б ловити чужі рядки.
    """
    html = client.get('/courses/').get_data(as_text=True)
    pane = html.split('data-schedule-pane="list"')[1]
    pane = pane.split('data-schedule-pane="calendar"')[0]
    start = pane.find(f'aria-label="{title}"')
    assert start != -1, f'рядка розкладу «{title}» не знайдено'
    return pane[start:pane.find('</a>', start)]


def test_schedule_row_names_the_level_that_differs_from_the_course(client):
    course, _inst = _pair('Курс з поглибленою датою', course_level=2,
                          instance_level=3)
    db.session.commit()

    item = _schedule_item(client, course.title)

    assert 'iprm-schedule__tag--level' in item
    assert 'Рівень 3/3' in item


def test_schedule_row_stays_silent_when_the_date_follows_the_course(client):
    """Рівень курсу вже стоїть на картці курсу в каталозі вище."""
    course, _inst = _pair('Курс без власного рівня дати', course_level=2)
    db.session.commit()

    item = _schedule_item(client, course.title)

    assert 'iprm-schedule__tag--level' not in item
