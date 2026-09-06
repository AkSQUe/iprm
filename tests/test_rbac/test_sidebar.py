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
    text = SIDEBAR.read_text(encoding='utf-8')
    body = text.split('<nav', 1)[1]
    links = re.findall(r"<a href=\"\{\{ url_for\('admin\.\w+'", body)
    gates = re.findall(r'\{% if can(?:_any)?\(', body)
    assert len(links) > 25
    # кожен пункт + кожна група мають свій if
    assert len(gates) >= len(links) + body.count('admin-sidebar__group-title')


def test_sidebar_shows_only_permitted_links(app, client):
    role = Role(name='t_sidebar', display_name='Т')
    role.permissions.append(Permission.query.filter_by(name='courses.view').one())
    role.permissions.append(Permission.query.filter_by(name='dashboard.view').one())
    db.session.add(role)
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
    for name in ('dashboard.view', 'users.view'):
        role.permissions.append(Permission.query.filter_by(name=name).one())
    db.session.add(role)
    db.session.flush()
    _login(client, make_user_with_role('t_dash'))
    resp = client.get('/admin/')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/users')
