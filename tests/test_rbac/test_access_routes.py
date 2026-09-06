from app.extensions import db
from app.models.rbac import Role
from app.rbac import registry
from tests.support.rbac import make_super_admin, make_user_with_role


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _viewer_with(*perms):
    role = Role(name='t_access_' + '_'.join(p.replace('.', '') for p in perms), display_name='T')
    from app.models.rbac import Permission
    for p in perms:
        role.permissions.append(Permission.query.filter_by(name=p).one())
    db.session.add(role)
    db.session.flush()
    return make_user_with_role(role.name)


def test_matrix_page_renders_all_permissions_and_roles(client):
    _login(client, make_super_admin())
    html = client.get('/admin/access').get_data(as_text=True)
    assert 'Матриця прав' in html
    for name in ('courses.view', 'access.assign', 'registrations.refund'):
        assert f'data-permission="{name}"' in html
    for role in ('Супер-адміністратор', 'Менеджер', 'Спостерігач'):
        assert role in html
    assert html.count('data-group-toggle=') == len(registry.GROUPS)


def test_matrix_readonly_for_access_view_only(client):
    _login(client, _viewer_with('access.view'))
    html = client.get('/admin/access').get_data(as_text=True)
    assert 'data-readonly="1"' in html
    assert 'data-bulk=' not in html


def test_toggle_permission_via_api(client):
    _login(client, make_super_admin())
    role = Role.query.filter_by(name='viewer').one()
    before = len(role.permissions)
    resp = client.put('/admin/access/api/matrix', json={
        'role_id': role.id, 'permission': 'courses.manage', 'granted': True})
    assert resp.status_code == 200
    assert resp.get_json()['role_count'] == before + 1
    resp = client.put('/admin/access/api/matrix', json={
        'role_id': role.id, 'permission': 'courses.manage', 'granted': False})
    assert resp.get_json()['role_count'] == before


def test_toggle_super_admin_is_400(client):
    _login(client, make_super_admin())
    sa = Role.query.filter_by(name='super_admin').one()
    resp = client.put('/admin/access/api/matrix', json={
        'role_id': sa.id, 'permission': 'courses.view', 'granted': False})
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_bulk_module(client):
    _login(client, make_super_admin())
    role = Role.query.filter_by(name='viewer').one()
    resp = client.post('/admin/access/api/matrix/bulk', json={
        'role_id': role.id, 'module': 'blog', 'mode': 'all'})
    assert resp.status_code == 200
    assert set(resp.get_json()['granted']) == {'blog.view', 'blog.manage', 'blog.delete'}
    resp = client.post('/admin/access/api/matrix/bulk', json={
        'role_id': role.id, 'module': 'blog', 'mode': 'none'})
    assert resp.get_json()['granted'] == []
    # повернути дефолт viewer
    client.put('/admin/access/api/matrix', json={
        'role_id': role.id, 'permission': 'blog.view', 'granted': True})


def test_api_forbidden_without_manage(client):
    _login(client, _viewer_with('access.view'))
    role = Role.query.filter_by(name='viewer').one()
    resp = client.put('/admin/access/api/matrix', json={
        'role_id': role.id, 'permission': 'courses.manage', 'granted': True})
    assert resp.status_code == 403
    assert resp.get_json() == {'error': 'forbidden'}


def test_unknown_role_is_404(client):
    _login(client, make_super_admin())
    resp = client.put('/admin/access/api/matrix', json={
        'role_id': 999999, 'permission': 'courses.view', 'granted': True})
    assert resp.status_code == 404
