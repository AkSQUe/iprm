"""Збереження спеціальностей курсу через адмінську форму."""
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.specialty import Specialty
from app.models.user import User


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'spec-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    # Прибираємо за собою: інакше валиться test_api_v1_clients.
    db.session.delete(user)
    db.session.commit()


@pytest.fixture
def rows():
    db.session.add_all([
        Specialty(code='alerholohiia', name='Алергологія', section='medical',
                  sort_order=2),
        Specialty(code='stara-nazva', name='Стара назва', section='medical',
                  sort_order=99, is_active=False),
    ])
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _course(**kwargs):
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=uuid4().hex[:8], **kwargs)
    db.session.add(course)
    db.session.commit()
    return course


def test_form_saves_selected_codes(client, admin, rows):
    _login(client, admin)
    course = _course()
    response = client.post(f'/admin/courses/{course.id}/edit', data={
        'title': course.title, 'slug': course.slug, 'event_type': 'seminar',
        'bpr_specialty_codes': ['alerholohiia'],
    }, follow_redirects=True)
    assert response.status_code == 200
    assert db.session.get(Course, course.id).bpr_specialty_codes == ['alerholohiia']


def test_form_rejects_unknown_code(client, admin, rows):
    _login(client, admin)
    course = _course()
    client.post(f'/admin/courses/{course.id}/edit', data={
        'title': course.title, 'slug': course.slug, 'event_type': 'seminar',
        'bpr_specialty_codes': ['no-such-code'],
    })
    assert db.session.get(Course, course.id).bpr_specialty_codes in (None, [])


def test_course_with_deactivated_code_still_saves(client, admin, rows):
    _login(client, admin)
    course = _course(bpr_specialty_codes=['stara-nazva'])
    response = client.post(f'/admin/courses/{course.id}/edit', data={
        'title': 'Нова назва курсу', 'slug': course.slug, 'event_type': 'seminar',
        'bpr_specialty_codes': ['stara-nazva'],
    }, follow_redirects=True)
    assert response.status_code == 200
    saved = db.session.get(Course, course.id)
    assert saved.title == 'Нова назва курсу'
    assert saved.bpr_specialty_codes == ['stara-nazva']
