"""Реєстр прав: єдине джерело для БД, матриці й декораторів."""
import pytest

from app.rbac import registry


def test_permission_names_are_unique_and_well_formed():
    names = [n for m in registry.MODULES for n in m.permission_names()]
    assert len(names) == len(set(names))
    for name in names:
        module, action = name.split('.', 1)
        assert module in registry.MODULES_BY_NAME
        assert action in registry.ACTIONS


def test_every_module_has_view_or_manage_and_known_group():
    groups = {key for key, _ in registry.GROUPS}
    for module in registry.MODULES:
        assert module.group in groups, module.name
        assert 'view' in module.actions or 'manage' in module.actions, module.name


def test_sensitive_actions_live_only_where_spec_says():
    owners = {
        'refund': {'registrations'}, 'settings': {'meta_leads'},
        'keys': {'integrations'}, 'restore': {'backup'},
        'receive': {'notifications'}, 'assign': {'access'},
    }
    for action, expected in owners.items():
        actual = {m.name for m in registry.MODULES if action in m.actions}
        assert actual == expected, action


def test_role_defaults_reference_existing_permissions():
    for role in registry.ROLES:
        for name in role.defaults:
            assert name in registry.ALL_PERMISSION_NAMES, (role.name, name)


def test_admin_defaults_exclude_access_settings_and_keys():
    admin = next(r for r in registry.ROLES if r.name == 'admin')
    for forbidden in ('access.view', 'access.manage', 'access.assign',
                      'settings.manage', 'integrations.keys',
                      'backup.restore', 'backup.delete'):
        assert forbidden not in admin.defaults
    assert 'courses.manage' in admin.defaults
    assert 'registrations.refund' in admin.defaults


def test_viewer_gets_only_views_outside_system():
    viewer = next(r for r in registry.ROLES if r.name == 'viewer')
    assert viewer.defaults
    for name in viewer.defaults:
        assert name.endswith('.view')
        assert registry.module_of(name).group not in ('system', 'access')


def test_super_admin_has_no_defaults_because_it_bypasses():
    sa = next(r for r in registry.ROLES if r.name == registry.SUPER_ADMIN)
    assert sa.defaults == frozenset()


def test_role_colors_come_from_palette():
    for role in registry.ROLES:
        assert role.color in registry.ROLE_COLORS


def test_labels_and_lookup():
    assert registry.permission_label('courses.manage') == 'Курси: Керування'
    assert registry.action_label('courses.manage') == 'Керування'
    assert registry.module_of('courses.manage').label == 'Курси'
    with pytest.raises(ValueError):
        registry.assert_known('nope.view')


def test_grouped_modules_follow_group_order():
    groups = registry.grouped_modules()
    assert [key for key, _, _ in groups] == [key for key, _ in registry.GROUPS]
    assert all(modules for _, _, modules in groups)


def test_entry_permission_is_view_or_manage():
    assert registry.MODULES_BY_NAME['courses'].entry_permission == 'courses.view'
    assert registry.MODULES_BY_NAME['settings'].entry_permission == 'settings.manage'
    assert registry.MODULES_BY_NAME['dashboard'].endpoint is None
    assert registry.MODULES_BY_NAME['translations'].endpoint is None


def test_entry_endpoints_exist_and_are_gated_by_entry_permission(app):
    """Сторінка-вхід кожного модуля існує і стоїть під правом входу: за
    цим переліком дашборд обирає, куди вести користувача."""
    targets = registry.entry_targets()
    assert targets[0] == ('courses.view', 'admin.courses_list')
    for permission, endpoint in targets:
        view = app.view_functions.get(endpoint)
        assert view is not None, endpoint
        assert permission in view._rbac_permissions, (endpoint, permission)
