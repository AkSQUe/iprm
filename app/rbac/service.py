"""Перевірка прав, синк реєстру в БД, операції над ролями.

Кеш ефективних прав живе в ``g`` і вмирає з запитом: правка матриці
впливає на інших користувачів із їхнього наступного запиту, міжзапитного
кешу немає навмисно.
"""
import logging
import re

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


# ------------------------------------------------------------ операції

_SLUG_MAX = 50


def _log(actor, message, *args):
    audit_logger.info('RBAC %s: ' + message, getattr(actor, 'email', '?'), *args)


def _permission(name):
    if name not in registry.ALL_PERMISSION_NAMES:
        raise AccessError(f'Невідоме право: {name}')
    perm = Permission.query.filter_by(name=name).first()
    if perm is None:
        raise AccessError(f'Право {name} ще не в базі: виконайте flask rbac sync')
    return perm


def _assert_editable(role):
    if role.name == registry.SUPER_ADMIN:
        raise AccessError('Права супер-адміністратора не редагуються')


def set_role_permission(role, name, granted, actor):
    _assert_editable(role)
    perm = _permission(name)
    has = perm in role.permissions
    if granted and not has:
        role.permissions.append(perm)
    elif not granted and has:
        role.permissions.remove(perm)
    db.session.flush()
    _log(actor, '%s %s -> %s', 'grant' if granted else 'revoke', name, role.name)


def set_module_permissions(role, module_name, granted, actor):
    _assert_editable(role)
    module = registry.MODULES_BY_NAME.get(module_name)
    if module is None:
        raise AccessError(f'Невідомий модуль: {module_name}')
    names = set(module.permission_names())
    present = {p.name: p for p in role.permissions}
    if granted:
        for name in names - set(present):
            role.permissions.append(_permission(name))
    else:
        for name in names & set(present):
            role.permissions.remove(present[name])
    db.session.flush()
    _log(actor, 'module %s %s -> %s', module_name, 'all' if granted else 'none', role.name)
    return sorted(p.name for p in role.permissions if p.name in names)


def reset_role_to_defaults(role, actor):
    _assert_editable(role)
    spec = registry.ROLES_BY_NAME.get(role.name)
    if spec is None or not role.is_system:
        raise AccessError('Скидання до дефолтів є лише у системних ролей')
    role.permissions.clear()
    _grant_names(role, spec.defaults)
    db.session.flush()
    _log(actor, 'reset role %s to defaults', role.name)


def _validate_role_fields(display_name, color, sort_order):
    if not (display_name or '').strip():
        raise AccessError('Назва ролі обов\'язкова')
    if color not in registry.ROLE_COLORS:
        raise AccessError('Колір має бути з палітри')
    if not isinstance(sort_order, int) or not 0 <= sort_order <= 1000:
        raise AccessError('Порядок: ціле число від 0 до 1000')


def _validate_slug(name):
    if not name or len(name) > _SLUG_MAX or not re.fullmatch(r'[a-z][a-z0-9_]*', name):
        raise AccessError('Код ролі: малі латинські літери, цифри, підкреслення')
    if Role.query.filter_by(name=name).first() is not None:
        raise AccessError(f'Роль з кодом {name} уже існує')


def create_role(name, display_name, description, color, sort_order, actor, copy_from=None):
    _validate_slug(name)
    _validate_role_fields(display_name, color, sort_order)
    role = Role(name=name, display_name=display_name.strip(),
                description=(description or '').strip() or None,
                color=color, sort_order=sort_order, is_system=False)
    db.session.add(role)
    db.session.flush()
    if copy_from is not None:
        names = (registry.ALL_PERMISSION_NAMES if copy_from.name == registry.SUPER_ADMIN
                 else [p.name for p in copy_from.permissions])
        _grant_names(role, names)
        db.session.flush()
    _log(actor, 'create role %s (copy_from=%s)', name, getattr(copy_from, 'name', None))
    return role


def update_role(role, display_name, description, color, sort_order, actor, name=None):
    _validate_role_fields(display_name, color, sort_order)
    if name and name != role.name and not role.is_system:
        _validate_slug(name)
        role.name = name
    role.display_name = display_name.strip()
    role.description = (description or '').strip() or None
    role.color = color
    role.sort_order = sort_order
    db.session.flush()
    _log(actor, 'update role %s', role.name)


def holders_count(role):
    return UserRole.query.filter_by(role_id=role.id).count()


def delete_role(role, actor):
    if role.is_system:
        raise AccessError('Системну роль видалити не можна')
    count = holders_count(role)
    if count:
        raise AccessError(f'У ролі ще {count} носіїв: спочатку зніміть її з них')
    name = role.name
    db.session.delete(role)
    db.session.flush()
    _log(actor, 'delete role %s', name)


def assign_roles(user, role_ids, actor):
    """Замінити набір ролей користувача. Запобіжники з розділу 6.5 спеки."""
    role_ids = set(role_ids)
    roles = Role.query.filter(Role.id.in_(role_ids)).all() if role_ids else []
    if len(roles) != len(role_ids):
        raise AccessError('Невідома роль у запиті')
    sa_role = Role.query.filter_by(name=registry.SUPER_ADMIN).one()
    current_ids = {r.id for r in user.roles}
    had_sa = sa_role.id in current_ids
    will_sa = sa_role.id in role_ids

    if had_sa != will_sa and not is_super_admin(actor):
        raise AccessError('Видавати або забирати super_admin може лише super_admin')
    if had_sa and not will_sa:
        if user.id == actor.id:
            raise AccessError('Не можна зняти super_admin із себе')
        if UserRole.query.filter_by(role_id=sa_role.id).count() <= 1:
            raise AccessError('Це останній super_admin: спершу призначте іншого')

    for row in UserRole.query.filter_by(user_id=user.id).all():
        if row.role_id not in role_ids:
            db.session.delete(row)
    for role_id in role_ids - current_ids:
        db.session.add(UserRole(user_id=user.id, role_id=role_id, assigned_by=actor.id))
    db.session.flush()
    db.session.expire(user, ['roles'])
    invalidate_cache()
    _log(actor, 'assign roles %s -> user %s', sorted(r.name for r in roles), user.email)
