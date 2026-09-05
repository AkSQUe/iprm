"""Декоратор перевіряється прямим викликом обгорнутої функції в
test_request_context: реєструвати пробний блупринт на спільному app не
можна (Flask 3 забороняє setup після першого запиту)."""
import pytest
from flask_login import login_user
from werkzeug.exceptions import Forbidden

from app.rbac.decorators import permission_required
from tests.support.rbac import make_super_admin, make_user_with_role

page = permission_required('courses.view')(lambda: 'ok')
either = permission_required('courses.manage', 'blog.manage')(lambda: 'ok')


def test_anonymous_redirected_to_login(app):
    with app.test_request_context('/admin/x'):
        resp = page()
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']


def test_viewer_sees_page_but_not_manage(app):
    with app.test_request_context('/admin/x'):
        login_user(make_user_with_role('viewer'))
        assert page() == 'ok'
        with pytest.raises(Forbidden):
            either()


def test_any_of_names_is_enough(app):
    with app.test_request_context('/admin/x'):
        login_user(make_user_with_role('content_editor'))
        assert either() == 'ok'


def test_super_admin_passes_everything(app):
    with app.test_request_context('/admin/x'):
        login_user(make_super_admin())
        assert either() == 'ok'


def test_json_request_gets_json_403(app):
    with app.test_request_context('/admin/access/api/x',
                                  headers={'Accept': 'application/json'}):
        login_user(make_user_with_role('viewer'))
        resp, status = either()
        assert status == 403
        assert resp.get_json() == {'error': 'forbidden'}


def test_json_anonymous_gets_401(app):
    with app.test_request_context('/admin/access/api/x',
                                  headers={'Accept': 'application/json'}):
        resp, status = either()
        assert status == 401


def test_decorator_marks_view_and_rejects_unknown_permission():
    assert either._rbac_permissions == ('courses.manage', 'blog.manage')
    with pytest.raises(ValueError):
        permission_required('nope.view')
    with pytest.raises(ValueError):
        permission_required()
