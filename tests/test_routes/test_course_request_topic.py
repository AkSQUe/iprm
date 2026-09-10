"""Намір заявки: «чекаю на нову дату» проти «розкажіть про курс».

Порожній блок дат веде на ту саму форму заявки, що й «отримати програму».
Без позначки наміру адмін бачить дві однакові заявки й не знає, кому
писати про нову дату, а кому -- надсилати програму. Позначка живе в
message: окрема колонка вимагала б міграції заради одного прапорця.
"""
import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_request import CourseRequest

INTENT_LINE = 'Чекає на нову дату проведення.'


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """Ліміт на POST заявки живий і потрібний, але тут заважає двічі.

    Він вичерпується вже на кількох заявках цього файлу, а лічильник
    спільний на всю сесію -- тож без вимкнення падає ще й сусідній
    test_course_request_fields, який просто йде наступним.
    """
    from app.extensions import limiter
    limiter.enabled = False
    yield
    limiter.enabled = True


def _course(slug):
    course = Course(slug=slug, title='Курс заявки', is_active=True)
    db.session.add(course)
    db.session.commit()
    return course


def _post(client, course, **overrides):
    data = {'email': 'lead@example.com', 'consent': '1'}
    data.update(overrides)
    return client.post(f'/courses/{course.slug}/request', data=data,
                       follow_redirects=True)


def test_new_date_topic_is_recorded(client):
    course = _course('topic-new-date')
    assert _post(client, course, topic='new_date').status_code == 200

    req = CourseRequest.query.filter_by(course_id=course.id).one()
    assert req.message == INTENT_LINE


def test_topic_is_kept_alongside_the_visitor_message(client):
    course = _course('topic-with-message')
    _post(client, course, topic='new_date', message='Чи буде у Львові?')

    req = CourseRequest.query.filter_by(course_id=course.id).one()
    assert req.message.startswith(INTENT_LINE)
    assert 'Чи буде у Львові?' in req.message


def test_unknown_topic_is_ignored(client):
    """Чужий topic не повинен ані падати, ані писати сміття в заявку."""
    course = _course('topic-junk')
    assert _post(client, course, topic='junk',
                 message='Просто питання').status_code == 200

    req = CourseRequest.query.filter_by(course_id=course.id).one()
    assert req.message == 'Просто питання'


def test_absent_topic_leaves_message_untouched(client):
    course = _course('topic-none')
    _post(client, course, message='Просто питання')

    req = CourseRequest.query.filter_by(course_id=course.id).one()
    assert req.message == 'Просто питання'


def test_empty_schedule_form_carries_the_topic(client):
    """Форма на сторінці без відкритих дат мусить нести позначку наміру."""
    course = _course('topic-form')
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'name="topic" value="new_date"' in html


def test_form_has_no_topic_when_dates_are_open(client, app):
    from datetime import datetime, timedelta, timezone
    from app.models.course_instance import CourseInstance

    course = _course('topic-form-open')
    db.session.add(CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
        max_participants=10,
    ))
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'name="topic"' not in html
