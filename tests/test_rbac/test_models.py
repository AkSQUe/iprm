from app.extensions import db
from app.models.rbac import Permission, Role, UserRole
from app.models.user import User


def test_role_permissions_and_user_roles_roundtrip(db_session):
    role = Role(name='t_role', display_name='Тест', color='blue')
    perm = Permission(name='courses.view', module='courses')
    role.permissions.append(perm)
    user = User.create_with_password('rbac-model@test.com', 'password123')
    db.session.add(role)
    db.session.flush()
    db.session.add(UserRole(user_id=user.id, role_id=role.id))
    db.session.flush()
    db.session.expire(user, ['roles'])

    assert [r.name for r in user.roles] == ['t_role']
    assert user.is_staff is True
    assert [p.name for p in user.roles[0].permissions] == ['courses.view']


def test_user_without_roles_is_not_staff(db_session):
    user = User.create_with_password('rbac-plain@test.com', 'password123')
    db.session.flush()
    assert user.roles == []
    assert user.is_staff is False


def test_role_defaults(db_session):
    role = Role(name='t_defaults', display_name='Д')
    db.session.add(role)
    db.session.flush()
    assert role.color == 'gray'
    assert role.is_system is False
    assert role.sort_order == 100
