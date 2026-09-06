from app.extensions import db
from app.models.rbac import Role
from tests.support.rbac import make_super_admin, make_user_with_role


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_user_detail_shows_roles_form_and_badges(client):
    boss = make_super_admin()
    target = make_user_with_role('viewer')
    _login(client, boss)
    html = client.get(f'/admin/users/{target.id}').get_data(as_text=True)
    assert 'badge--role' in html
    assert 'Спостерігач' in html
    assert f'/admin/users/{target.id}/roles' in html


def test_assign_roles_via_form(client):
    boss = make_super_admin()
    target = make_user_with_role('viewer')
    manager = Role.query.filter_by(name='manager').one()
    _login(client, boss)
    resp = client.post(f'/admin/users/{target.id}/roles', data={'roles': [str(manager.id)]})
    assert resp.status_code == 302
    db.session.expire(target, ['roles'])
    assert [r.name for r in target.roles] == ['manager']


def test_assign_requires_permission(client):
    actor = make_user_with_role('admin')  # admin не має access.assign
    target = make_user_with_role('viewer')
    _login(client, actor)
    resp = client.post(f'/admin/users/{target.id}/roles', data={'roles': []})
    assert resp.status_code == 403


def test_guard_message_flashes(client):
    boss = make_super_admin()
    _login(client, boss)
    resp = client.post(f'/admin/users/{boss.id}/roles', data={'roles': []}, follow_redirects=True)
    assert 'Не можна зняти super_admin із себе' in resp.get_data(as_text=True)


def test_users_list_filters_by_role(client):
    boss = make_super_admin()
    make_user_with_role('marketer', email='marketer-filter@test.com')
    _login(client, boss)
    html = client.get('/admin/users?role=marketer').get_data(as_text=True)
    assert 'marketer-filter@test.com' in html
    assert boss.email not in html
