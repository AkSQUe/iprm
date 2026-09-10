"""Вибір типу в адмінці курсу: активні + чинний, навіть застарілий.

Головна регресія тут -- курс зі старим типом («Курс», «Вебінар»).
Якщо його значення не потрапляє в choices, WTForms валить сабміт із
"Not a valid choice", і адміністратор не збереже навіть правку
заголовка, що типу взагалі не стосується.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.user import User
from tests.support.rbac import grant_role


@pytest.fixture
def admin():
    u = User.create_with_password(
        f'ch-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _course(event_type):
    course = Course(title='Курс', slug=f'ch-{uuid4().hex[:6]}',
                    is_active=True, event_type=event_type)
    db.session.add(course)
    db.session.flush()
    return course


def test_new_course_form_offers_only_active_types(client, admin):
    _login(client, admin)
    html = client.get('/admin/courses/new').get_data(as_text=True)
    assert 'value="scientific_conference"' in html
    assert 'value="professional_school"' in html
    assert 'value="webinar"' not in html, 'застарілий тип не пропонується'


def test_edit_form_keeps_deactivated_current_type(client, admin):
    _login(client, admin)
    course = _course('course')
    html = client.get(f'/admin/courses/{course.id}/edit').get_data(as_text=True)
    assert 'value="course"' in html
    assert 'застарілий' in html


def test_saving_course_with_deactivated_type_succeeds(client, admin):
    """Правка заголовка не мусить впиратись у застарілий тип."""
    _login(client, admin)
    course = _course('webinar')
    r = client.post(f'/admin/courses/{course.id}/edit', data={
        'title': 'Оновлений заголовок',
        'slug': course.slug,
        'event_type': 'webinar',
        'difficulty_level': '0',
        'base_price': '0',
    }, follow_redirects=True)

    assert r.status_code == 200
    db.session.expire(course)
    assert course.title == 'Оновлений заголовок'
    assert course.event_type == 'webinar'


def test_course_can_be_switched_to_new_bpr_type(client, admin):
    _login(client, admin)
    course = _course('course')
    client.post(f'/admin/courses/{course.id}/edit', data={
        'title': course.title,
        'slug': course.slug,
        'event_type': 'skills_training',
        'difficulty_level': '0',
        'base_price': '0',
    }, follow_redirects=True)

    db.session.expire(course)
    assert course.event_type == 'skills_training'
