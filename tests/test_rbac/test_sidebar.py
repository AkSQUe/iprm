import re
from pathlib import Path

from app.extensions import db
from app.models.rbac import Permission, Role
from tests.support.rbac import make_user_with_role

SIDEBAR = Path('app/templates/admin/partials/_sidebar.html')


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_every_sidebar_link_is_gated():
    """Кожен пункт стоїть за власним {% if can('...') %}, і для сторінки-входу
    модуля це саме право входу з реєстру (не підрахунок, а пари)."""
    from app.rbac import registry

    text = SIDEBAR.read_text(encoding='utf-8')
    body = text.split('<nav', 1)[1]
    by_endpoint = {m.endpoint: m for m in registry.MODULES if m.endpoint}
    token = re.compile(
        r"\{% if can\('([^']+)'\) %\}|(\{% endif %\})|<a href=\"\{\{ url_for\('(admin\.\w+)'"
    )
    open_gate = None
    links = 0
    for m in token.finditer(body):
        gate, endif, endpoint = m.groups()
        if gate:
            open_gate = gate
        elif endif:
            open_gate = None
        else:
            links += 1
            assert open_gate, f'пункт {endpoint} без {{% if can(...) %}}'
            registry.assert_known(open_gate)
            module = by_endpoint.get(endpoint)
            if module is not None:
                assert open_gate == module.entry_permission, (endpoint, open_gate)
    assert links > 25
    assert len(re.findall(r'\{% if can_any\(', body)) == body.count('admin-sidebar__group-title')


def test_dashboard_falls_back_to_any_registry_entry(app, client):
    """Користувач лише з materials.view раніше отримував 403 на «/admin»."""
    role = Role(name='t_dash_materials', display_name='Т')
    db.session.add(role)
    for name in ('dashboard.view', 'materials.view'):
        role.permissions.append(Permission.query.filter_by(name=name).one())
    db.session.flush()
    _login(client, make_user_with_role('t_dash_materials'))
    resp = client.get('/admin/')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/materials')


def test_sidebar_shows_only_permitted_links(app, client):
    role = Role(name='t_sidebar', display_name='Т')
    db.session.add(role)
    role.permissions.append(Permission.query.filter_by(name='courses.view').one())
    role.permissions.append(Permission.query.filter_by(name='dashboard.view').one())
    db.session.flush()
    _login(client, make_user_with_role('t_sidebar'))

    html = client.get('/admin/courses').get_data(as_text=True)
    assert '/admin/courses' in html
    assert 'Контент' in html
    assert '/admin/users' not in html
    assert 'Продажі' not in html
    assert 'Система' not in html


def test_super_admin_sees_access_link(app, client):
    from tests.support.rbac import make_super_admin
    _login(client, make_super_admin())
    html = client.get('/admin/courses').get_data(as_text=True)
    assert '/admin/access' in html


def test_dashboard_redirects_to_first_visible_page(app, client):
    role = Role(name='t_dash', display_name='Т')
    db.session.add(role)
    for name in ('dashboard.view', 'users.view'):
        role.permissions.append(Permission.query.filter_by(name=name).one())
    db.session.flush()
    _login(client, make_user_with_role('t_dash'))
    resp = client.get('/admin/')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/users')
