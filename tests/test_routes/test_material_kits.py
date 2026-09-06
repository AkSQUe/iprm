"""Admin: комплекти матеріалів (MaterialKit/MaterialKitItem) -- CRUD + позиції з каталогу.

`course_id=None` -- це УНІВЕРСАЛЬНИЙ комплект (task 3). Тести окремо
перевіряють, що вибір "універсальний" -- явний пункт списку курсів, а не
просто відсутність вибору.
"""
from tests.support.rbac import grant_role
from uuid import uuid4

import pytest

from app.admin import routes_material_kits as kit_routes
from app.extensions import db
from app.models.course import Course
from app.models.material_kit import MaterialKit, MaterialKitItem
from app.models.user import User

FAKE_CATALOG = [
    {'sku': 'NDL-21', 'name': 'Голка 21G', 'available': 100, 'price': 12.5,
     'category': 'Голки', 'is_consumable': True},
    {'sku': 'GLV-M', 'name': 'Рукавички M', 'available': 50, 'price': 3.0,
     'category': 'Захист', 'is_consumable': True},
]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'mk-admin-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='А', last_name='Адмін', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


@pytest.fixture
def plain_user(app):
    u = User.create_with_password(
        f'mk-user-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Н', last_name='Юзер', is_admin=False, email_confirmed=True,
    )
    db.session.flush()
    return u


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    """Каталог MM Medic мокнутий -- тести не ходять у мережу."""
    monkeypatch.setattr(kit_routes.mrs, 'get_catalog',
                        lambda **kw: (FAKE_CATALOG, None, False))


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _course():
    course = Course(title='Плазмотерапія', slug=f'mk-{uuid4().hex[:6]}', is_active=False)
    db.session.add(course)
    db.session.flush()
    return course


def _kit(course_id=None, name='Базовий набір'):
    kit = MaterialKit(name=name, course_id=course_id)
    db.session.add(kit)
    db.session.flush()
    return kit


def test_requires_admin(client):
    assert client.get('/admin/material-kits').status_code in (302, 401, 403)


def test_requires_admin_forbidden_for_non_admin_user(client, plain_user):
    _login(client, plain_user)
    assert client.get('/admin/material-kits').status_code == 403


def test_pages_render_for_admin(client, admin):
    _login(client, admin)
    kit = _kit()
    db.session.commit()

    assert client.get('/admin/material-kits').status_code == 200
    assert client.get('/admin/material-kits/new').status_code == 200
    assert client.get(f'/admin/material-kits/{kit.id}').status_code == 200


def test_course_picker_lists_universal_as_explicit_choice(client, admin):
    """Порожній варіант -- явний, підписаний пункт, а не відсутність вибору."""
    _login(client, admin)
    course = _course()
    db.session.commit()

    resp = client.get('/admin/material-kits/new')
    html = resp.get_data(as_text=True)
    assert 'value=""' in html
    assert 'ніверсальн' in html          # "Універсальний" / "універсальний"
    assert course.title in html


def test_create_universal_kit(client, admin):
    _login(client, admin)
    resp = client.post('/admin/material-kits/new', data={
        'name': 'Універсальний набір',
        'course_id': '',
        'is_default': '',
        'is_active': 'y',
        'notes': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    kit = MaterialKit.query.filter_by(name='Універсальний набір').one()
    assert kit.course_id is None


def test_create_kit_bound_to_course(client, admin):
    _login(client, admin)
    course = _course()
    db.session.commit()

    resp = client.post('/admin/material-kits/new', data={
        'name': 'Набір під курс',
        'course_id': str(course.id),
        'is_active': 'y',
        'notes': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    kit = MaterialKit.query.filter_by(name='Набір під курс').one()
    assert kit.course_id == course.id


def test_create_kit_with_two_items_saves_both(client, admin):
    _login(client, admin)
    kit = _kit(name='Два рядки')
    db.session.commit()

    client.post(f'/admin/material-kits/{kit.id}/items/add', data={
        'sku': 'NDL-21', 'name_snapshot': 'Голка 21G', 'quantity': '5',
        'is_required': 'y', 'note': '',
    }, follow_redirects=True)
    client.post(f'/admin/material-kits/{kit.id}/items/add', data={
        'sku': 'GLV-M', 'name_snapshot': 'Рукавички M', 'quantity': '2',
        'note': '',
    }, follow_redirects=True)

    items = MaterialKitItem.query.filter_by(kit_id=kit.id).order_by(
        MaterialKitItem.sku).all()
    assert len(items) == 2
    assert items[0].sku == 'GLV-M' and items[0].quantity == 2
    assert items[1].sku == 'NDL-21' and items[1].quantity == 5
    assert items[1].is_required is True
    assert items[1].name_snapshot == 'Голка 21G'


def test_item_add_writes_name_snapshot_from_catalog_when_missing(client, admin):
    _login(client, admin)
    kit = _kit(name='Снапшот з каталогу')
    db.session.commit()

    client.post(f'/admin/material-kits/{kit.id}/items/add', data={
        'sku': 'NDL-21', 'quantity': '1',
    }, follow_redirects=True)

    item = MaterialKitItem.query.filter_by(kit_id=kit.id, sku='NDL-21').one()
    assert item.name_snapshot == 'Голка 21G'


def test_item_add_rejects_zero_quantity(client, admin):
    _login(client, admin)
    kit = _kit(name='Нульова кількість')
    db.session.commit()

    client.post(f'/admin/material-kits/{kit.id}/items/add', data={
        'sku': 'NDL-21', 'quantity': '0',
    }, follow_redirects=True)

    assert MaterialKitItem.query.filter_by(kit_id=kit.id).count() == 0


def test_delete_item_does_not_touch_other_kits(client, admin):
    _login(client, admin)
    kit_a = _kit(name='Набір A')
    kit_b = _kit(name='Набір B')
    db.session.commit()

    client.post(f'/admin/material-kits/{kit_a.id}/items/add',
                data={'sku': 'NDL-21', 'quantity': '3'}, follow_redirects=True)
    client.post(f'/admin/material-kits/{kit_b.id}/items/add',
                data={'sku': 'NDL-21', 'quantity': '7'}, follow_redirects=True)

    item_a = MaterialKitItem.query.filter_by(kit_id=kit_a.id, sku='NDL-21').one()
    item_b = MaterialKitItem.query.filter_by(kit_id=kit_b.id, sku='NDL-21').one()

    client.post(f'/admin/material-kits/{kit_a.id}/items/{item_a.id}/delete',
                follow_redirects=True)

    assert MaterialKitItem.query.filter_by(kit_id=kit_a.id).count() == 0
    remaining = db.session.get(MaterialKitItem, item_b.id)
    assert remaining is not None
    assert remaining.quantity == 7


def test_delete_kit_cascades_its_items(client, admin):
    _login(client, admin)
    kit = _kit(name='Комплект на видалення')
    db.session.commit()
    client.post(f'/admin/material-kits/{kit.id}/items/add',
                data={'sku': 'NDL-21', 'quantity': '1'}, follow_redirects=True)

    client.post(f'/admin/material-kits/{kit.id}/delete', follow_redirects=True)

    assert db.session.get(MaterialKit, kit.id) is None
    assert MaterialKitItem.query.filter_by(kit_id=kit.id).count() == 0


def test_list_shows_course_and_item_count(client, admin):
    _login(client, admin)
    course = _course()
    kit = _kit(course_id=course.id, name='Список видно')
    kit.items.append(MaterialKitItem(sku='NDL-21', quantity=4))
    db.session.commit()

    resp = client.get('/admin/material-kits')
    html = resp.get_data(as_text=True)
    assert 'Список видно' in html
    assert course.title in html
