"""Перевірка прав, синк реєстру в БД, операції над ролями.

Кеш ефективних прав живе в ``g`` і вмирає з запитом: правка матриці
впливає на інших користувачів із їхнього наступного запиту, міжзапитного
кешу немає навмисно.
"""
import logging

from flask import g, has_request_context
from sqlalchemy import or_, select

from app.extensions import db
from app.models.rbac import Permission, Role, UserRole, role_permissions
from . import registry

audit_logger = logging.getLogger('audit')

_CACHE_PREFIX = '_rbac_perms_'


class AccessError(ValueError):
    """Запобіжник відхилив зміну. Текст придатний для flash."""


def _cache_get(key):
    return g.get(key) if has_request_context() else None


def _cache_set(key, value):
    if has_request_context():
        setattr(g, key, value)


def invalidate_cache():
    """Скинути кеш прав поточного запиту (після зміни ролей у цьому ж запиті)."""
    if not has_request_context():
        return
    for key in [k for k in list(g.__dict__) if k.startswith(_CACHE_PREFIX)]:
        g.pop(key)


def effective_permissions(user):
    key = f'{_CACHE_PREFIX}{user.id}'
    cached = _cache_get(key)
    if cached is None:
        rows = db.session.execute(
            select(Permission.name)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == role_permissions.c.role_id)
            .where(UserRole.user_id == user.id)
        ).scalars().all()
        cached = frozenset(rows)
        _cache_set(key, cached)
    return cached


def is_super_admin(user):
    return any(r.name == registry.SUPER_ADMIN for r in user.roles)


def _usable(user):
    return bool(getattr(user, 'is_authenticated', False)) and bool(getattr(user, 'is_active', False))


def has_permission(user, name):
    if not _usable(user):
        return False
    if is_super_admin(user):
        return True
    return name in effective_permissions(user)


def has_any(user, names):
    if not _usable(user):
        return False
    if is_super_admin(user):
        return True
    granted = effective_permissions(user)
    return any(n in granted for n in names)


def users_with_permission(name):
    """Активні користувачі з ефективним правом (super_admin включно)."""
    from app.models.user import User
    return (
        User.query
        .filter(User.is_active.is_(True))
        .filter(User.roles.any(or_(
            Role.name == registry.SUPER_ADMIN,
            Role.permissions.any(Permission.name == name),
        )))
        .order_by(User.id)
        .all()
    )


def _grant_names(role, names):
    perms = Permission.query.filter(Permission.name.in_(list(names))).all()
    present = {p.name for p in role.permissions}
    for perm in perms:
        if perm.name not in present:
            role.permissions.append(perm)


def sync():
    """Права з реєстру -> БД; відсутні системні ролі -> створити з дефолтами.

    Наявних ролей і їхніх прав НЕ торкається: матриця головна. Не комітить.
    """
    wanted = set(registry.ALL_PERMISSION_NAMES)
    existing = {p.name: p for p in Permission.query.all()}

    added = sorted(wanted - set(existing))
    for name in added:
        db.session.add(Permission(name=name, module=name.split('.', 1)[0]))
    removed = sorted(set(existing) - wanted)
    for name in removed:
        db.session.delete(existing[name])
    db.session.flush()

    created = []
    for spec in registry.ROLES:
        if Role.query.filter_by(name=spec.name).first() is not None:
            continue
        role = Role(name=spec.name, display_name=spec.display_name,
                    description=spec.description, color=spec.color,
                    is_system=True, sort_order=spec.sort_order)
        db.session.add(role)
        db.session.flush()
        _grant_names(role, spec.defaults)
        created.append(spec.name)
    db.session.flush()
    return {'added': added, 'removed': removed, 'roles_created': created}
