"""Фасад RBAC: один імпорт для перевірок і операцій.

Реалізація розділена за відповідальністю:

* ``app.rbac.access`` -- читання: ефективні права, кеш на запит,
  super_admin-обхід, вибірка користувачів за правом;
* ``app.rbac.roles`` -- запис: синк реєстру, матриця, CRUD ролей,
  призначення ролей із запобіжниками.

Модуль лишається точкою входу для маршрутів, CLI й тестів, щоб імпорти
``from app.rbac import service`` не змінювались.
"""
from .access import (  # noqa: F401
    effective_permissions, has_any, has_permission, invalidate_cache,
    is_super_admin, users_with_permission,
)
from .roles import (  # noqa: F401
    NO_ROLE_FILTER, RESERVED_SLUGS, AccessError, SystemActor, assign_roles,
    create_role, delete_role, holders_count, reset_role_to_defaults,
    set_module_permissions, set_role_permission, sync, update_role,
)

__all__ = [
    'effective_permissions', 'has_any', 'has_permission', 'invalidate_cache',
    'is_super_admin', 'users_with_permission',
    'NO_ROLE_FILTER', 'RESERVED_SLUGS', 'AccessError', 'SystemActor',
    'assign_roles', 'create_role', 'delete_role', 'holders_count',
    'reset_role_to_defaults', 'set_module_permissions', 'set_role_permission',
    'sync', 'update_role',
]
