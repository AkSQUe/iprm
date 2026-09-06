from app.extensions import db
from app.models.rbac import Permission, Role
from app.rbac import registry, service


def test_sync_is_idempotent_and_complete(app):
    result = service.sync()
    assert result == {'added': [], 'removed': [], 'roles_created': []}
    assert {p.name for p in Permission.query.all()} == set(registry.ALL_PERMISSION_NAMES)
    assert {r.name for r in Role.query.filter_by(is_system=True)} >= {
        r.name for r in registry.ROLES}


def test_sync_removes_orphan_permission_and_keeps_role_edits(app):
    db.session.add(Permission(name='ghost.view', module='ghost'))
    viewer = Role.query.filter_by(name='viewer').one()
    extra = Permission.query.filter_by(name='courses.manage').one()
    viewer.permissions.append(extra)
    db.session.flush()

    result = service.sync()

    assert result['removed'] == ['ghost.view']
    assert Permission.query.filter_by(name='ghost.view').first() is None
    assert extra in Role.query.filter_by(name='viewer').one().permissions
    viewer.permissions.remove(extra)
    db.session.flush()


def test_sync_removes_orphan_permission_granted_to_role(app):
    """Право, вилучене з реєстру, зникає з role_permissions разом із собою:
    ondelete='CASCADE' на permission_id (app/models/rbac.py) прибирає
    видачу автоматично, коли sync() видаляє сам рядок permissions."""
    viewer = Role.query.filter_by(name='viewer').one()
    before = {p.name for p in viewer.permissions}
    ghost = Permission(name='ghost.view', module='ghost')
    db.session.add(ghost)
    db.session.flush()
    viewer.permissions.append(ghost)
    db.session.flush()
    assert 'ghost.view' in {p.name for p in viewer.permissions}

    result = service.sync()

    assert result['removed'] == ['ghost.view']
    assert Permission.query.filter_by(name='ghost.view').first() is None
    db.session.expire(viewer, ['permissions'])
    assert {p.name for p in viewer.permissions} == before


def test_sync_creates_missing_system_role_with_defaults(app):
    role = Role.query.filter_by(name='marketer').one()
    db.session.delete(role)
    db.session.flush()

    result = service.sync()

    assert result['roles_created'] == ['marketer']
    created = Role.query.filter_by(name='marketer').one()
    spec = registry.ROLES_BY_NAME['marketer']
    assert {p.name for p in created.permissions} == set(spec.defaults)
    assert created.is_system is True
    assert created.color == spec.color
