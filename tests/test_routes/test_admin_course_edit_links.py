"""Число реєстрацій у картці курсу веде в перелік зареєстрованих.

Дзеркалить розклад проведень (`instances.html`): нуль лишається текстом,
непорожнє число -- посилання на `instance_registrations`.
"""
import re
from datetime import datetime, timedelta, timezone
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
        f'cel-{_uid()}@test.com', 'password123',
        first_name='C', last_name='E', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


@pytest.fixture
def course(app, admin):
    c = Course(title=f'Курс {_uid()}', slug=f'cel-{_uid()}', is_active=True)
    db.session.add(c)
    db.session.commit()
    yield c
    db.session.rollback()
    db.session.delete(db.session.merge(c))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _instance(course):
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(inst)
    db.session.commit()
    return inst


def _add_reg(instance):
    user = User.create_with_password(
        f'p-{_uid()}@test.com', 'password123', first_name='P', last_name='X',
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380671110002',
        specialty='T', workplace='Клініка', status='pending', payment_status='unpaid',
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def test_registration_count_links_to_instance_registrations(client, admin, course):
    inst = _instance(course)
    reg = _add_reg(inst)
    user_id = reg.user_id
    _login(client, admin)
    try:
        html = client.get(f'/admin/courses/{course.id}/edit').get_data(as_text=True)
        href = f'/admin/instances/{inst.id}/registrations'
        assert re.search(rf'<a href="{re.escape(href)}">\s*1\s*</a>', html)
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.get(User, user_id))
        db.session.delete(db.session.merge(inst))
        db.session.commit()


def test_zero_registrations_stays_plain_text(client, admin, course):
    inst = _instance(course)
    _login(client, admin)
    try:
        html = client.get(f'/admin/courses/{course.id}/edit').get_data(as_text=True)
        href = f'/admin/instances/{inst.id}/registrations'
        assert not re.search(rf'<a href="{re.escape(href)}">\s*0\s*</a>', html)
    finally:
        db.session.delete(db.session.merge(inst))
        db.session.commit()
