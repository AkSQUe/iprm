from app.models.rbac import Role
from tests.support.rbac import make_super_admin


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_create_role_with_copy(client):
    _login(client, make_super_admin())
    viewer = Role.query.filter_by(name='viewer').one()
    resp = client.post('/admin/access/roles/new', data={
        'name': 't_form_role', 'display_name': 'Форма', 'description': 'опис',
        'color': 'teal', 'sort_order': '70', 'copy_from': str(viewer.id),
    }, follow_redirects=False)
    assert resp.status_code == 302
    role = Role.query.filter_by(name='t_form_role').one()
    assert role.color == 'teal'
    assert {p.name for p in role.permissions} == {p.name for p in viewer.permissions}


def test_create_role_rejects_bad_slug(client):
    _login(client, make_super_admin())
    resp = client.post('/admin/access/roles/new', data={
        'name': 'Bad Slug', 'display_name': 'X', 'color': 'teal', 'sort_order': '70', 'copy_from': '0',
    })
    assert resp.status_code == 200
    assert Role.query.filter_by(name='Bad Slug').first() is None


def test_edit_system_role_changes_label_only(client):
    _login(client, make_super_admin())
    role = Role.query.filter_by(name='content_editor').one()
    resp = client.post(f'/admin/access/roles/{role.id}/edit', data={
        'name': 'hacked', 'display_name': 'Редактор', 'description': '',
        'color': 'blue', 'sort_order': '30', 'copy_from': '0',
    })
    assert resp.status_code == 302
    role = Role.query.filter_by(name='content_editor').one()
    assert role.display_name == 'Редактор'
    role.display_name = 'Редактор контенту'


def test_reset_and_delete(client):
    _login(client, make_super_admin())
    marketer = Role.query.filter_by(name='marketer').one()
    assert client.post(f'/admin/access/roles/{marketer.id}/reset').status_code == 302
    assert client.post(f'/admin/access/roles/{marketer.id}/delete').status_code == 302
    assert Role.query.filter_by(name='marketer').first() is not None  # системна
    client.post('/admin/access/roles/new', data={
        'name': 't_to_delete', 'display_name': 'D', 'color': 'gray', 'sort_order': '90', 'copy_from': '0'})
    role = Role.query.filter_by(name='t_to_delete').one()
    client.post(f'/admin/access/roles/{role.id}/delete')
    assert Role.query.filter_by(name='t_to_delete').first() is None
