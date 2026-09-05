"""Ролі та права адмін-панелі.

Права оголошені в коді (app/rbac/registry.py) і синкаються сюди командою
``flask rbac sync``. Розклад роль -> права (role_permissions) живе лише в
БД і правиться матрицею /admin/access: синк його не перезаписує.
"""
from app.extensions import db
from app.models.mixins import BigIntPK, utcnow

role_permissions = db.Table(
    'role_permissions',
    db.Column('role_id', db.BigInteger,
              db.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_id', db.BigInteger,
              db.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True),
)


class Role(db.Model):
    __tablename__ = 'roles'

    id = db.Column(BigIntPK, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    # Ім'я з палітри registry.ROLE_COLORS, не hex: клас .role-color--<name>
    # виставляє колір із токенів, і inline-стилів не потрібно.
    color = db.Column(db.String(20), nullable=False, default='gray',
                      server_default='gray')
    # Системну роль не можна видалити або перейменувати (slug); підпис,
    # колір і права правити можна.
    is_system = db.Column(db.Boolean, nullable=False, default=False,
                          server_default=db.false())
    sort_order = db.Column(db.Integer, nullable=False, default=100,
                           server_default='100')
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    permissions = db.relationship(
        'Permission', secondary=role_permissions, lazy='select',
        backref=db.backref('roles', lazy='select'),
    )
    # Носії ролі. viewonly, бо в user_roles є службові колонки: записи
    # робляться через UserRole, а не через цей список.
    # primaryjoin/secondaryjoin явно: user_roles має ДВІ колонки, що ведуть
    # на users (user_id і assigned_by), тож автовиведення зв'язку неоднозначне.
    users = db.relationship(
        'User', secondary='user_roles', viewonly=True, lazy='select',
        primaryjoin='Role.id == UserRole.role_id',
        secondaryjoin='User.id == UserRole.user_id',
    )

    def __repr__(self):
        return f'<Role {self.name}>'


class Permission(db.Model):
    __tablename__ = 'permissions'

    id = db.Column(BigIntPK, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    module = db.Column(db.String(50), nullable=False, index=True)

    def __repr__(self):
        return f'<Permission {self.name}>'


class UserRole(db.Model):
    __tablename__ = 'user_roles'

    user_id = db.Column(db.BigInteger,
                        db.ForeignKey('users.id', ondelete='CASCADE'),
                        primary_key=True)
    role_id = db.Column(db.BigInteger,
                        db.ForeignKey('roles.id', ondelete='CASCADE'),
                        primary_key=True)
    assigned_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    assigned_by = db.Column(db.BigInteger,
                            db.ForeignKey('users.id', ondelete='SET NULL'))

    def __repr__(self):
        return f'<UserRole user={self.user_id} role={self.role_id}>'
