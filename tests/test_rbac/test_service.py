from flask import g

from app.extensions import db
from app.models.rbac import Permission, Role, UserRole
from app.models.user import User
from app.rbac import service
from tests.support.rbac import grant_role, make_super_admin, make_user_with_role


def _custom_role(name, *perms):
    role = Role(name=name, display_name=name)
    for p in perms:
        role.permissions.append(Permission.query.filter_by(name=p).one())
    db.session.add(role)
    db.session.flush()
    return role


def test_super_admin_passes_without_permission_rows(app):
    with app.test_request_context():
        user = make_super_admin()
        assert service.is_super_admin(user)
        assert service.has_permission(user, 'settings.manage')
        assert service.has_permission(user, 'access.assign')


def test_effective_permissions_union_of_roles(app):
    with app.test_request_context():
        _custom_role('t_a', 'courses.view')
        _custom_role('t_b', 'blog.view', 'blog.manage')
        user = make_user_with_role('t_a')
        grant_role(user, 't_b')
        assert service.effective_permissions(user) == frozenset(
            {'courses.view', 'blog.view', 'blog.manage'})
        assert service.has_permission(user, 'blog.manage')
        assert not service.has_permission(user, 'courses.manage')
        assert service.has_any(user, ('courses.manage', 'blog.view'))
        assert not service.has_any(user, ('courses.manage', 'users.view'))


def test_inactive_or_anonymous_has_nothing(app):
    with app.test_request_context():
        user = make_user_with_role('viewer')
        user.is_active = False
        db.session.flush()
        assert not service.has_permission(user, 'courses.view')

        class Anon:
            is_authenticated = False
            is_active = False
        assert not service.has_permission(Anon(), 'courses.view')


def test_permissions_cached_per_request(app):
    with app.test_request_context():
        user = make_user_with_role('viewer')
        first = service.effective_permissions(user)
        # Пряма зміна в БД без інвалідації: кеш у g лишає старий набір.
        role = Role.query.filter_by(name='viewer').one()
        role.permissions.append(Permission.query.filter_by(name='courses.manage').one())
        db.session.flush()
        assert service.effective_permissions(user) is first
        service.invalidate_cache()
        assert 'courses.manage' in service.effective_permissions(user)
        # Прибрати за собою: viewer -- спільна роль сесії тестів.
        role.permissions.remove(Permission.query.filter_by(name='courses.manage').one())
        db.session.flush()


def test_users_with_permission_includes_super_admins(app):
    with app.test_request_context():
        sa = make_super_admin()
        admin = make_user_with_role('admin')
        viewer = make_user_with_role('viewer')
        emails = {u.email for u in service.users_with_permission('notifications.receive')}
        assert sa.email in emails
        assert admin.email in emails
        assert viewer.email not in emails
