"""Фільтр списку курсів за видом заходу.

Лічильник «Вжито» в довіднику веде саме сюди: питання «що я зламаю, якщо
деактивую цей тип» інакше не має відповіді в інтерфейсі.
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
        f'ctf-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    return u


@pytest.fixture
def two_courses():
    seminar = Course(title='Семінарний курс', slug=f'ctf-s-{uuid4().hex[:6]}',
                     is_active=True, event_type='seminar')
    congress = Course(title='Конгресний курс', slug=f'ctf-c-{uuid4().hex[:6]}',
                      is_active=True, event_type='congress')
    db.session.add_all([seminar, congress])
    db.session.commit()
    yield seminar, congress
    db.session.delete(seminar)
    db.session.delete(congress)
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_filter_narrows_list_to_one_type(client, admin, two_courses):
    _login(client, admin)
    seminar, congress = two_courses

    html = client.get('/admin/courses?event_type=congress').get_data(as_text=True)

    assert congress.title in html
    assert seminar.title not in html


def test_no_filter_shows_both(client, admin, two_courses):
    _login(client, admin)
    seminar, congress = two_courses

    html = client.get('/admin/courses').get_data(as_text=True)

    assert seminar.title in html
    assert congress.title in html


def test_unknown_code_falls_back_to_no_filter(client, admin, two_courses):
    """Старе посилання з видаленим кодом не має давати порожній екран."""
    _login(client, admin)
    seminar, congress = two_courses

    html = client.get('/admin/courses?event_type=сміття').get_data(as_text=True)

    assert seminar.title in html
    assert congress.title in html
