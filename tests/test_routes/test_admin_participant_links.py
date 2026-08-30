"""ПІБ і email учасника в реєстрах реєстрацій ведуть у деталі учасника.

ПІБ -- у редагування учасника (`participant_edit`): зараз ця дія лежить
під меню «...», хоч це найчастіша дія над рядком. Email -- у картку
контакту (`user_detail`). Перевіряються обидві сторінки реєстрів:
загальний реєстр і реєстр одного проведення.
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
        f'pl-{_uid()}@test.com', 'password123',
        first_name='P', last_name='L', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


@pytest.fixture
def instance(app, admin):
    course = Course(title=f'Курс {_uid()}', slug=f'pl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(inst)
    db.session.flush()
    db.session.commit()
    yield inst
    db.session.rollback()
    EventRegistration.query.filter_by(instance_id=inst.id).delete()
    db.session.delete(db.session.merge(inst))
    db.session.delete(db.session.merge(course))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _add_reg(instance, first_name='Тест', last_name='Учасник'):
    user = User.create_with_password(
        f'p-{_uid()}@test.com', 'password123',
        first_name=first_name, last_name=last_name,
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380671110002',
        specialty='T', workplace='Клініка', status='pending', payment_status='unpaid',
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def test_registrations_all_links_name_and_email(client, admin, instance):
    reg = _add_reg(instance)
    user_id = reg.user_id
    _login(client, admin)
    try:
        # Реєстр звужений до заходу тесту -- сесія тестів ділить одну БД.
        html = client.get(
            f'/admin/registrations?instance_id={instance.id}&scope=all'
        ).get_data(as_text=True)
        edit_href = f'/admin/registrations/{reg.id}/edit'
        detail_href = f'/admin/users/{user_id}'
        assert re.search(rf'<a href="{re.escape(edit_href)}">\s*Тест Учасник', html)
        assert re.search(
            rf'<a href="{re.escape(detail_href)}">\s*{re.escape(reg.user.email)}', html,
        )
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.get(User, user_id))
        db.session.commit()


def test_instance_registrations_links_name_and_email(client, admin, instance):
    reg = _add_reg(instance)
    user_id = reg.user_id
    _login(client, admin)
    try:
        html = client.get(
            f'/admin/instances/{instance.id}/registrations'
        ).get_data(as_text=True)
        edit_href = f'/admin/registrations/{reg.id}/edit'
        detail_href = f'/admin/users/{user_id}'
        assert re.search(rf'<a href="{re.escape(edit_href)}">\s*Тест Учасник', html)
        assert re.search(
            rf'<a href="{re.escape(detail_href)}">\s*{re.escape(reg.user.email)}', html,
        )
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.get(User, user_id))
        db.session.commit()
