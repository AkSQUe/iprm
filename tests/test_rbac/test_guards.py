"""Fail-closed: в'юха адмінки без оголошеного права не проходить CI."""
from app.rbac import registry
from tests.support.rbac import make_user_with_role


def test_every_admin_endpoint_declares_permission(app):
    missing = []
    for endpoint, view in app.view_functions.items():
        if not endpoint.startswith('admin.'):
            continue
        names = getattr(view, '_rbac_permissions', None)
        if not names:
            missing.append(endpoint)
            continue
        for name in names:
            assert name in registry.ALL_PERMISSION_NAMES, (endpoint, name)
    assert not missing, 'в\'юхи без @permission_required: ' + ', '.join(sorted(missing))


def test_blueprint_rejects_user_without_roles(app, client):
    from app.extensions import db
    from app.models.user import User
    user = User.create_with_password('norole@test.com', 'password123', email_confirmed=True)
    db.session.flush()
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)
    assert client.get('/admin/courses').status_code == 403


def test_blueprint_redirects_anonymous(client):
    resp = client.get('/admin/courses')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_viewer_reaches_list(app, client):
    with client.session_transaction() as s:
        s['_user_id'] = str(make_user_with_role('viewer').id)
    assert client.get('/admin/courses').status_code == 200
