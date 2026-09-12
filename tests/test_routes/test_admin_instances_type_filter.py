"""Фільтр реєстру проведень за видом заходу БПР.

Вид дати ЕФЕКТИВНИЙ: власний, а порожній -- курсовий. Тому фільтр не може
бути простим `CourseInstance.event_type == code`, як у курсах: він
пропустив би всі дати, що вид успадковують, тобто переважну більшість.
Саме ця помилка й робить такий фільтр небезпечним -- екран виглядає
правдоподібно порожнім, а не зламаним.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.user import User
from tests.support.rbac import grant_role

SLUG_PREFIX = 'itf-'


@pytest.fixture(autouse=True)
def clean(app):
    def _wipe():
        courses = Course.query.filter(
            Course.slug.like(f'{SLUG_PREFIX}%')).all()
        if courses:
            CourseInstance.query.filter(
                CourseInstance.course_id.in_([c.id for c in courses])).delete(
                    synchronize_session=False)
            Course.query.filter(Course.id.in_([c.id for c in courses])).delete(
                synchronize_session=False)
            db.session.commit()
    _wipe()
    yield
    _wipe()


@pytest.fixture
def admin():
    u = User.create_with_password(
        f'itf-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _course(event_type, title):
    c = Course(title=title, slug=f'{SLUG_PREFIX}{uuid4().hex[:6]}',
               is_active=True, base_price=0, event_type=event_type)
    db.session.add(c)
    db.session.flush()
    return c


def _instance(course, event_type=None):
    inst = CourseInstance(
        course_id=course.id, event_type=event_type, status='published',
        event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=900),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _filtered(client, code):
    """Лише <tbody> таблиці.

    Назви курсів стоять ще й в <option> фільтра «Курс», тож перевірка по
    всій сторінці завжди знаходила б їх і нічого не доводила.
    """
    html = client.get(
        f'/admin/instances?event_type={code}').get_data(as_text=True)
    start = html.find('<tbody>')
    return html[start:html.find('</tbody>', start)] if start != -1 else ''


def test_filter_catches_the_date_that_overrides_the_type(client, admin):
    _login(client, admin)
    _instance(_course('seminar', 'Курс-семінар ITFA'), event_type='training')
    db.session.commit()

    assert 'Курс-семінар ITFA' in _filtered(client, 'training')


def test_filter_catches_the_date_that_inherits_the_type(client, admin):
    """Головна пастка: успадкованих дат більшість, і саме їх легко згубити."""
    _login(client, admin)
    _instance(_course('training', 'Курс-тренінг ITFB'))
    db.session.commit()

    assert 'Курс-тренінг ITFB' in _filtered(client, 'training')


def test_filter_drops_the_date_that_overrides_away_from_the_type(client, admin):
    """Курс -- тренінг, але ця дата проводиться семінаром."""
    _login(client, admin)
    _instance(_course('training', 'Курс-тренінг ITFC'), event_type='seminar')
    db.session.commit()

    assert 'Курс-тренінг ITFC' not in _filtered(client, 'training')


def test_filter_drops_unrelated_dates(client, admin):
    _login(client, admin)
    _instance(_course('seminar', 'Курс-семінар ITFD'))
    db.session.commit()

    assert 'Курс-семінар ITFD' not in _filtered(client, 'training')


def test_garbage_value_falls_back_to_no_filter(client, admin):
    """?event_type=<сміття> має дати порожній фільтр, а не порожній екран."""
    _login(client, admin)
    _instance(_course('seminar', 'Курс-семінар ITFE'))
    db.session.commit()

    assert 'Курс-семінар ITFE' in _filtered(client, 'not-a-real-type')


def test_the_filter_control_is_offered_on_the_page(client, admin):
    _login(client, admin)
    html = client.get('/admin/instances').get_data(as_text=True)
    assert 'name="event_type"' in html
