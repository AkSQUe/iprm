import pytest

from app.extensions import db
from app.models.rbac import Role, UserRole
from app.rbac import registry, service
from app.rbac.service import AccessError
from tests.support.rbac import grant_role, make_super_admin, make_user_with_role


def _perm_names(role):
    return {p.name for p in role.permissions}


def test_toggle_permission_and_module_bulk(app):
    with app.test_request_context():
        actor = make_super_admin()
        role = service.create_role('t_ops', 'Ops', '', 'teal', 100, actor)
        service.set_role_permission(role, 'courses.view', True, actor)
        assert _perm_names(role) == {'courses.view'}
        service.set_role_permission(role, 'courses.view', False, actor)
        assert _perm_names(role) == set()
        granted = service.set_module_permissions(role, 'blog', True, actor)
        assert set(granted) == {'blog.view', 'blog.manage', 'blog.delete'}
        assert service.set_module_permissions(role, 'blog', False, actor) == []


def test_super_admin_matrix_is_locked(app):
    with app.test_request_context():
        actor = make_super_admin()
        sa = Role.query.filter_by(name='super_admin').one()
        with pytest.raises(AccessError):
            service.set_role_permission(sa, 'courses.view', True, actor)
        with pytest.raises(AccessError):
            service.set_module_permissions(sa, 'courses', True, actor)


def test_unknown_permission_rejected(app):
    with app.test_request_context():
        actor = make_super_admin()
        role = Role.query.filter_by(name='viewer').one()
        with pytest.raises(AccessError):
            service.set_role_permission(role, 'nope.view', True, actor)


def test_reset_restores_defaults(app):
    with app.test_request_context():
        actor = make_super_admin()
        role = Role.query.filter_by(name='marketer').one()
        service.set_role_permission(role, 'settings.manage', True, actor)
        service.reset_role_to_defaults(role, actor)
        assert _perm_names(role) == set(registry.ROLES_BY_NAME['marketer'].defaults)
        custom = service.create_role('t_reset', 'R', '', 'gray', 100, actor)
        with pytest.raises(AccessError):
            service.reset_role_to_defaults(custom, actor)


def test_create_role_copies_permissions_and_validates(app):
    with app.test_request_context():
        actor = make_super_admin()
        src = Role.query.filter_by(name='viewer').one()
        role = service.create_role('t_copy', 'Копія', 'опис', 'blue', 60, actor, copy_from=src)
        assert _perm_names(role) == _perm_names(src)
        assert role.is_system is False
        with pytest.raises(AccessError):
            service.create_role('viewer', 'Дубль', '', 'blue', 60, actor)
        with pytest.raises(AccessError):
            service.create_role('t_bad', 'X', '', 'pink', 60, actor)


def test_update_system_role_keeps_slug(app):
    with app.test_request_context():
        actor = make_super_admin()
        role = Role.query.filter_by(name='viewer').one()
        service.update_role(role, 'Глядач', 'опис', 'teal', 55, actor, name='renamed')
        assert role.name == 'viewer'
        assert role.display_name == 'Глядач'
        role.display_name = 'Спостерігач'
        role.color = 'gray'
        role.sort_order = 50
        db.session.flush()


def test_delete_role_rules(app):
    with app.test_request_context():
        actor = make_super_admin()
        with pytest.raises(AccessError):
            service.delete_role(Role.query.filter_by(name='viewer').one(), actor)
        role = service.create_role('t_del', 'D', '', 'gray', 100, actor)
        holder = make_user_with_role('t_del')
        with pytest.raises(AccessError):
            service.delete_role(role, actor)
        service.assign_roles(holder, set(), actor)
        service.delete_role(role, actor)
        assert Role.query.filter_by(name='t_del').first() is None


def test_assign_roles_guards(app):
    with app.test_request_context():
        boss = make_super_admin()
        second = make_super_admin()
        viewer_role = Role.query.filter_by(name='viewer').one()
        sa_role = Role.query.filter_by(name='super_admin').one()
        admin_role = Role.query.filter_by(name='admin').one()

        # зняти super_admin із себе не можна
        with pytest.raises(AccessError):
            service.assign_roles(boss, {viewer_role.id}, boss)
        # не-super_admin не роздає super_admin
        plain_admin = make_user_with_role('admin')
        target = make_user_with_role('viewer')
        with pytest.raises(AccessError):
            service.assign_roles(target, {sa_role.id}, plain_admin)
        # звичайне призначення
        service.assign_roles(target, {viewer_role.id, admin_role.id}, plain_admin)
        db.session.expire(target, ['roles'])
        assert {r.name for r in target.roles} == {'viewer', 'admin'}
        row = UserRole.query.filter_by(user_id=target.id, role_id=admin_role.id).one()
        assert row.assigned_by == plain_admin.id
        # останнього super_admin забрати не можна
        service.assign_roles(second, set(), boss)  # ще є boss
        others = UserRole.query.filter_by(role_id=sa_role.id).filter(UserRole.user_id != boss.id).all()
        for row in others:
            db.session.delete(row)
        db.session.flush()
        with pytest.raises(AccessError):
            service.assign_roles(boss, set(), second)
