"""Адмінка довідника спеціальностей: доступ, збереження, додавання, видалення."""
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
        f'sp-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    db.session.delete(user)
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


@pytest.fixture
def row():
    specialty = Specialty(code=f'kod-{uuid4().hex[:6]}', name='Алергологія',
                          section='medical', sort_order=2)
    db.session.add(specialty)
    db.session.commit()
    return specialty


def test_requires_permission(client):
    assert client.get('/admin/specialties').status_code in (302, 401, 403)


def test_list_renders_rows(client, admin, row):
    _login(client, admin)
    response = client.get('/admin/specialties')
    assert response.status_code == 200
    assert 'Алергологія' in response.get_data(as_text=True)


def test_add_creates_row_with_generated_code(client, admin):
    _login(client, admin)
    client.post('/admin/specialties/add',
                data={'name': 'Дитяча ендокринологія', 'section': 'medical'})
    assert Specialty.query.filter_by(code='dytiacha-endokrynolohiia').count() == 1


def test_add_rejects_empty_name(client, admin):
    _login(client, admin)
    before = Specialty.query.count()
    client.post('/admin/specialties/add', data={'name': '  ', 'section': 'medical'})
    assert Specialty.query.count() == before


def test_add_redirect_keeps_active_filters(client, admin):
    """Додавання рядка не повинно скидати фільтр, з яким адміністратор
    дивився список -- інакше він щоразу повертається на непрофільтрований
    довідник."""
    _login(client, admin)
    response = client.post(
        '/admin/specialties/add?section=pharmacy&state=active',
        data={'name': 'Дитяча ендокринологія', 'section': 'medical'},
    )
    assert response.status_code == 302
    assert 'section=pharmacy' in response.headers['Location']
    assert 'state=active' in response.headers['Location']


def test_save_writes_translation_and_flags(client, admin, row):
    _login(client, admin)
    response = client.post('/admin/specialties/save', data={
        f'row__{row.id}': '1',
        f'tr__ru__{row.id}': 'Аллергология',
        f'order__{row.id}': '7',
    })
    assert response.status_code == 302
    saved = db.session.get(Specialty, row.id)
    assert saved.t('name', lang='ru') == 'Аллергология'
    assert saved.sort_order == 7
    # Галка не прийшла у формі -- рядок деактивовано.
    assert saved.is_active is False


def test_delete_refuses_used_row(client, admin, row):
    _login(client, admin)
    course = Course(title='Курс', slug=f'c-{uuid4().hex[:6]}',
                    bpr_specialty_codes=[row.code])
    db.session.add(course)
    db.session.commit()

    client.post(f'/admin/specialties/{row.id}/delete')
    assert db.session.get(Specialty, row.id) is not None


def test_delete_removes_unused_row(client, admin, row):
    _login(client, admin)
    client.post(f'/admin/specialties/{row.id}/delete')
    assert db.session.get(Specialty, row.id) is None
