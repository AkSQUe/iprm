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


def test_edit_form_labels_field_as_extra_description(client, admin, rows):
    _login(client, admin)
    course = _course()
    html = client.get(f'/admin/courses/{course.id}/edit').get_data(as_text=True)
    assert 'Додатковий опис цільової аудиторії' in html


def test_edit_form_previews_selected_specialties(client, admin, rows):
    """Прев'ю показує те, що вийде на сторінці, ще до збереження."""
    _login(client, admin)
    course = _course(bpr_specialty_codes=['alerholohiia'])
    html = client.get(f'/admin/courses/{course.id}/edit').get_data(as_text=True)
    start = html.find('data-audience-preview')
    assert start != -1, "блоку прев'ю аудиторії немає у формі"
    preview = html[start:html.find('</div>', start)]
    assert 'Алергологія' in preview
    assert 'admin-audience-preview.js' in html


def test_create_form_renders_without_course(client, admin, rows):
    _login(client, admin)
    response = client.get('/admin/courses/new')
    assert response.status_code == 200
    assert 'data-audience-preview' in response.get_data(as_text=True)


def test_preview_keeps_submitted_codes_after_failed_validation(client, admin, rows):
    """Валідація впала -- прев'ю показує подане, а не збережене.

    Мультиселект після невдалого сабміту малюється з даних форми; якби
    прев'ю читало курс із БД, редактор бачив би два різні переліки в
    одній формі.
    """
    _login(client, admin)
    course = _course(bpr_specialty_codes=['stara-nazva'])
    html = client.post(f'/admin/courses/{course.id}/edit', data={
        'title': '', 'slug': course.slug, 'event_type': 'seminar',
        'bpr_specialty_codes': ['alerholohiia'],
    }).get_data(as_text=True)
    start = html.find('data-audience-preview')
    preview = html[start:html.find('</div>', start)]
    assert 'Алергологія' in preview
    assert 'Стара назва' not in preview


def test_preview_on_create_form_shows_submitted_codes(client, admin, rows):
    _login(client, admin)
    html = client.post('/admin/courses/new', data={
        'title': '', 'slug': 'nova', 'event_type': 'seminar',
        'bpr_specialty_codes': ['alerholohiia'],
    }).get_data(as_text=True)
    start = html.find('data-audience-preview')
    preview = html[start:html.find('</div>', start)]
    assert 'Алергологія' in preview
