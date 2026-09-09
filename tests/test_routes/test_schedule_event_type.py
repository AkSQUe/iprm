"""Розклад (публічний /courses/): вид заходу в секції «Графік курсів».

List і Calendar -- дві вьюхи одного й того самого проведення, тож обидві
мусять показувати ЕФЕКТИВНИЙ вид заходу (власний проведення, а якщо
порожній -- курсовий), а не курсовий безумовно. Інакше одна й та сама
подія називається по-різному залежно від того, яку вкладку відкрив
відвідувач.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance


def _pair(course_type='seminar', instance_type=None):
    course = Course(title='Розклад', slug=f'sched-{uuid4().hex[:6]}',
                    is_active=True, event_type=course_type)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, event_type=instance_type,
        status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=3),
    )
    db.session.add(inst)
    db.session.flush()
    return course, inst


def _schedule_list_pane(client):
    """Розмітка тільки вкладки «Список» розкладу (без картки курсу вище,
    де показ курсового типу -- правильна, окрема поведінка)."""
    html = client.get('/courses/').get_data(as_text=True)
    pane = html.split('data-schedule-pane="list"')[1]
    return pane.split('data-schedule-pane="calendar"')[0]


def test_list_view_shows_instance_override_not_course_type(client):
    """Курс -- семінар, проведення перевизначене на тренінг: у розкладі --
    тренінг, а не курсовий семінар. Картка курсу в каталозі (де курсовий
    тип лишається правильним) до перевірки не потрапляє."""
    course, _inst = _pair(course_type='seminar', instance_type='training')
    db.session.commit()

    pane = _schedule_list_pane(client)

    assert 'Тренінг' in pane
    assert 'Семінар' not in pane
