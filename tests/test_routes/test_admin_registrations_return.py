"""Повернення на те саме місце списку після дії в рядку.

Дія зі списку реєстрацій шле у next поточний URL з фільтрами і сторінкою.
Значення приходить із форми, тож перевіряємо і що чужий домен не пролізе.
"""
from tests.support.rbac import grant_role
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'ret-{_uid()}@test.com', 'password123',
        first_name='R', last_name='A', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


@pytest.fixture
def reg(app, admin):
    course = Course(title='Return Course', slug=f'ret-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='active', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    r = EventRegistration(
        user_id=admin.id, instance_id=inst.id, phone='+380000000000',
        specialty='T', workplace='T', status='pending', payment_status='unpaid',
    )
    db.session.add(r)
    db.session.flush()
    return r


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_action_returns_to_filtered_page(client, admin, reg):
    _login(client, admin)
    back = '/admin/registrations?scope=all&status=pending&page=3'
    r = client.post(
        f'/admin/registrations/{reg.id}/status',
        data={'status': 'confirmed', 'next': back},
    )
    assert r.status_code == 302
    assert r.headers['Location'].endswith(back)


def test_external_next_is_ignored(client, admin, reg):
    _login(client, admin)
    r = client.post(
        f'/admin/registrations/{reg.id}/status',
        data={'status': 'confirmed', 'next': 'https://evil.example/steal'},
    )
    assert r.status_code == 302
    assert 'evil.example' not in r.headers['Location']
    # Фолбек -- сторінка заходу, з якого прийшли.
    assert f'/admin/instances/{reg.instance_id}/registrations' in r.headers['Location']


def test_legacy_marker_still_works(client, admin, reg):
    """Сторінка зі старим маркером могла лишитись у кеші браузера."""
    _login(client, admin)
    r = client.post(
        f'/admin/registrations/{reg.id}/status',
        data={'status': 'confirmed', 'next': 'registrations_all'},
    )
    assert r.status_code == 302
    assert r.headers['Location'].endswith('/admin/registrations')
