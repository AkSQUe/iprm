"""Перевірка прав користувача і кеш на один запит.

Кеш ефективних прав живе в ``g`` і вмирає з запитом: правка матриці
впливає на інших користувачів із їхнього наступного запиту, міжзапитного
кешу немає навмисно. Операції над ролями (синк, матриця, призначення)
живуть у ``app.rbac.roles``; цей модуль лише читає.
"""
from flask import g, has_request_context
from sqlalchemy import or_, select

from app.extensions import db
from app.models.rbac import Permission, Role, UserRole, role_permissions
from . import registry

_CACHE_PREFIX = '_rbac_perms_'


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
    """Об'єднання прав усіх ролей користувача; один запит на HTTP-запит."""
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
    """Анонім або неактивний -> False; super_admin -> True без читання прав."""
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
