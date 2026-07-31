"""Адмінка довідника локацій: доступ, додавання, збереження, видалення."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.city import City
from app.models.user import User


@pytest.fixture
def admin():
    u = User.create_with_password(
        f'a-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _uniq(prefix):
    return f'{prefix}-{uuid4().hex[:6]}'


def test_requires_admin(client):
    assert client.get('/admin/cities').status_code in (302, 401, 403)


def test_add_creates_city_with_normalized_name(client, admin):
    _login(client, admin)
    name = _uniq('Харків')
    r = client.post('/admin/cities/add', data={'name': f'  {name}  '})
    assert r.status_code == 302

    city = City.query.filter_by(name_normalized=name.lower()).one()
    assert city.name == name


def test_add_rejects_empty_name(client, admin):
    _login(client, admin)
    before = City.query.count()
    client.post('/admin/cities/add', data={'name': '   '})
    assert City.query.count() == before


def test_add_is_idempotent_for_same_name(client, admin):
    _login(client, admin)
    name = _uniq('Львів')
    client.post('/admin/cities/add', data={'name': name})
    client.post('/admin/cities/add', data={'name': name.upper()})
    assert City.query.filter_by(name_normalized=name.lower()).count() == 1


def test_save_writes_translations(client, admin):
    _login(client, admin)
    name, ru = _uniq('Одеса'), _uniq('Одесса')
    client.post('/admin/cities/add', data={'name': name})
    city = City.query.filter_by(name_normalized=name.lower()).one()

    r = client.post('/admin/cities/save', data={f'tr__ru__{city.id}': ru})
    assert r.status_code == 302
    assert db.session.get(City, city.id).t('name', lang='ru') == ru


def test_save_empty_removes_translation(client, admin):
    _login(client, admin)
    name = _uniq('Дніпро')
    client.post('/admin/cities/add', data={'name': name})
    city = City.query.filter_by(name_normalized=name.lower()).one()
    client.post('/admin/cities/save', data={f'tr__ru__{city.id}': 'Днепр'})
    client.post('/admin/cities/save', data={f'tr__ru__{city.id}': ''})

    fetched = db.session.get(City, city.id)
    assert 'name' not in (fetched.translations.get('ru') or {})
    assert fetched.t('name', lang='ru') == name  # фолбек на укр


def test_delete_removes_city(client, admin):
    _login(client, admin)
    name = _uniq('Суми')
    client.post('/admin/cities/add', data={'name': name})
    city = City.query.filter_by(name_normalized=name.lower()).one()

    r = client.post(f'/admin/cities/{city.id}/delete')
    assert r.status_code == 302
    assert db.session.get(City, city.id) is None


def test_list_renders_rows_and_unknown_section(client, admin):
    _login(client, admin)
    name = _uniq('Вінниця')
    client.post('/admin/cities/add', data={'name': name})
    html = client.get('/admin/cities').get_data(as_text=True)
    assert name in html
    assert 'tr__ru__' in html and 'tr__en__' in html
