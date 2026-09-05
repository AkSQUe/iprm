# RBAC і матриця прав: план реалізації

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Замінити прапорець `users.is_admin` системою ролей і прав з матрицею на `/admin/access`, під якою стоять усі 261 в'юха адмінки.

**Architecture:** Права оголошені в коді (`app/rbac/registry.py`) і синкаються в БД командою `flask rbac sync`. Розклад роль-права живе в БД (`role_permissions`) і правиться лише матрицею. Кожна в'юха адмінки стоїть під `@permission_required('module.action')`, блупринт додатково пускає лише носіїв ролей, а тест-сторож не дає з'явитись в'юсі без права.

**Tech Stack:** Flask 3, Flask-SQLAlchemy, Alembic (Flask-Migrate), Flask-WTF, Jinja2, vanilla JS, CSS-токени дизайн-системи, pytest із SQLite in-memory.

**Spec:** `docs/superpowers/specs/2026-09-05-rbac-access-matrix-design.md`

## Global Constraints

- Жодних emoji в коді, жодних inline-стилів і inline-скриптів (CLAUDE.md).
- Компонентні класи (перемикач, крапка ролі, бейдж ролі) оголошуються ОДИН раз у компонентному CSS і показуються в каталозі `app/templates/design_system/_tab_admin.html`; сторінкові стилі лише у `page-admin-access.css` і лише розкладка.
- Кольори ролей зберігаються ІМЕНЕМ із палітри `red orange amber green teal blue violet gray`, не hex.
- Нове право, додане в реєстр, нікому не видається автоматично, крім `super_admin` через обхід.
- `flask rbac sync` не чіпає ролей, які вже є в БД, і їхніх прав.
- Комітити напряму в `main`; не пушити. Кожен коміт закінчується рядком `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Прогін тестів: `python -m pytest -q` з кореня репозиторію. Повний прогін після кожної задачі етапів 2 і далі.
- Тести, що створюють користувачів, не мусять лишати їх після себе (фікстура `db_session` відкочує транзакцію; додаткових комітів у БД не робити).
- Міграцію `rbac_20260905` НЕ застосовувати до dev або prod БД, доки не завершено Етап 3 (Task 8): до того коду ще потрібна колонка `is_admin`.

---

## Мапа файлів

Створюються:

- `app/rbac/__init__.py` — публічний API пакета і `init_app(app)` (Jinja-глобали, CLI).
- `app/rbac/registry.py` — модулі, дії, групи, ролі та їхні дефолти.
- `app/rbac/service.py` — ефективні права, перевірки, синк, операції над ролями з запобіжниками.
- `app/rbac/decorators.py` — `permission_required`.
- `app/rbac/cli.py` — `flask rbac sync`, `flask rbac status`.
- `app/models/rbac.py` — `Role`, `Permission`, `role_permissions`, `UserRole`.
- `migrations/versions/rbac_20260905.py`.
- `app/admin/routes_access.py` — сторінка матриці, JSON API, CRUD ролей.
- `app/templates/admin/access.html`, `app/templates/admin/access_role_form.html`.
- `app/static/js/admin-access-matrix.js`, `app/static/css/page-admin-access.css`.
- `tests/support/rbac.py` — хелпери для тестів.
- `tests/test_rbac/` — `test_registry.py`, `test_service.py`, `test_decorators.py`, `test_guards.py`, `test_sync.py`, `test_access_routes.py`, `test_sidebar.py`, `test_user_roles.py`.
- `docs/rbac.md`.

Змінюються: `app/__init__.py`, `app/models/__init__.py`, `app/models/user.py`, `app/admin/__init__.py`, усі `app/admin/routes*.py`, `app/admin/forms.py`, `app/templates/admin/partials/_sidebar.html`, `app/templates/partials/header.html`, `app/templates/partials/_posthog.html`, `app/templates/admin/users.html`, `app/templates/admin/user_detail.html`, `app/templates/admin/notifications_recipients.html`, `app/templates/design_system/_tab_admin.html`, `app/services/notification_recipients.py`, `app/services/xlsx_reports.py`, `app/admin/routes_meta_leads.py`, `app/models/material_reservation.py`, `app/static/css/common.css`, `app/static/css/admin.css`, `tests/conftest.py`, 68 тестових файлів, `.github/workflows/deploy.yml`, `README.md`, `docs/models.md`, `docs/routes.md`, `docs/deployment.md`.

Видаляється: `app/admin/decorators.py`.

---

# Етап 1. Ядро: реєстр, моделі, сервіс, CLI

### Task 1: Реєстр прав і ролей

**Files:**
- Create: `app/rbac/__init__.py` (порожній на цьому кроці), `app/rbac/registry.py`
- Test: `tests/test_rbac/__init__.py` (порожній), `tests/test_rbac/test_registry.py`

**Interfaces:**
- Produces: `registry.MODULES: tuple[Module]`, `registry.MODULES_BY_NAME`, `registry.GROUPS`, `registry.ACTIONS`, `registry.ALL_PERMISSION_NAMES: frozenset[str]`, `registry.SUPER_ADMIN = 'super_admin'`, `registry.ROLE_COLORS`, `registry.ROLES: tuple[RoleSpec]`, `registry.permission_label(name) -> str`, `registry.action_label(name) -> str`, `registry.module_of(name) -> Module`, `registry.grouped_modules() -> list[tuple[str, str, list[Module]]]`, `registry.assert_known(name)`.

- [ ] **Step 1: Написати тест реєстру**

```python
# tests/test_rbac/test_registry.py
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
```

- [ ] **Step 2: Запустити, переконатись, що падає**

Run: `python -m pytest tests/test_rbac/test_registry.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.rbac'`

- [ ] **Step 3: Написати реєстр**

```python
# app/rbac/__init__.py
"""RBAC адмін-панелі. Публічний API збирається в Task 4."""
```

```python
# app/rbac/registry.py
"""Реєстр прав адмін-панелі: єдине джерело для БД, матриці й декораторів.

Право має вигляд ``module.action``. Модуль збігається з пунктом сайдбару,
сторінки без власного пункту приклеєні до батька. Підписи живуть тут, а не
в БД: таблиця permissions зберігає лише ім'я й модуль.

Додати право до нової в'юхи: дописати дію в actions модуля (або новий
Module), поставити @permission_required на в'юху, виконати
``flask rbac sync``. Нікому, крім super_admin, право не видається
автоматично: видача робиться в матриці /admin/access.
"""
from dataclasses import dataclass

ACTIONS = {
    'view': 'Перегляд',
    'manage': 'Керування',
    'delete': 'Видалення',
    'export': 'Експорт',
    'import': 'Імпорт',
    'refund': 'Повернення коштів',
    'settings': 'Налаштування інтеграції',
    'keys': 'Ключі й секрети',
    'restore': 'Відновлення з копії',
    'receive': 'Службові листи',
    'assign': 'Призначення ролей',
}

GROUPS = (
    ('dashboard', 'Панель'),
    ('content', 'Контент'),
    ('sales', 'Продажі'),
    ('audience', 'Аудиторія'),
    ('tools', 'Інструменти'),
    ('system', 'Система'),
    ('access', 'Доступ'),
)
GROUP_LABELS = dict(GROUPS)


@dataclass(frozen=True)
class Module:
    name: str
    label: str
    group: str
    actions: tuple

    def permission_names(self):
        return tuple(f'{self.name}.{action}' for action in self.actions)


_VM = ('view', 'manage')
_VMD = ('view', 'manage', 'delete')

MODULES = (
    Module('dashboard', 'Панель', 'dashboard', ('view',)),
    Module('courses', 'Курси', 'content', ('view', 'manage', 'delete', 'export', 'import')),
    Module('instances', 'Розклад', 'content', ('view', 'manage', 'delete', 'export', 'import')),
    Module('online_courses', 'Онлайн-курси', 'content', _VM),
    Module('cities', 'Довідник локацій', 'content', _VMD),
    Module('quizzes', 'Тестування', 'content', _VMD),
    Module('course_requests', 'Запити на курси', 'content', ('view', 'manage', 'delete', 'export')),
    Module('b2b_requests', 'B2B-заявки', 'content', ('view', 'manage', 'export')),
    Module('meta_leads', 'Ліди Meta', 'content', ('view', 'manage', 'delete', 'export', 'settings')),
    Module('refund_requests', 'Заявки на повернення', 'content', ('view', 'manage', 'export')),
    Module('trainers', 'Тренери', 'content', _VMD),
    Module('blog', 'Блог', 'content', _VMD),
    Module('media', 'Медіа', 'content', _VMD),
    Module('translations', 'Переклади', 'content', ('manage', 'export', 'import')),
    Module('registrations', 'Реєстрації', 'sales', ('view', 'manage', 'export', 'import', 'refund')),
    Module('online_orders', 'Онлайн-курси: замовлення', 'sales', ('view', 'manage', 'export')),
    Module('certificates', 'Сертифікати', 'sales', ('view', 'manage', 'export')),
    Module('referrals', 'Реферали', 'sales', ('view', 'manage', 'export')),
    Module('promo_codes', 'Промокоди', 'sales', ('view', 'manage', 'delete', 'export')),
    Module('users', 'Користувачі', 'audience', ('view', 'export')),
    Module('reviews', 'Відгуки', 'audience', _VMD),
    Module('cert_generator', 'Генератор сертифікатів', 'tools', _VM),
    Module('marketing', 'Маркетинг', 'system', _VM),
    Module('notifications', 'Сповіщення', 'system', ('view', 'manage', 'export', 'receive')),
    Module('integrations', 'Інтеграції', 'system', ('view', 'manage', 'keys')),
    Module('webhooks', 'Webhook черга', 'system', _VMD),
    Module('materials', 'Резервування матеріалів', 'system', ('view', 'manage', 'delete', 'export', 'import')),
    Module('error_logs', 'Журнал помилок', 'system', ('view', 'manage', 'delete', 'export')),
    Module('perf', 'Швидкість сторінок', 'system', _VM),
    Module('design_system', 'Дизайн-система', 'system', ('view',)),
    Module('settings', 'Налаштування', 'system', ('manage',)),
    Module('backup', 'Резервні копії', 'system', ('view', 'manage', 'delete', 'export', 'restore')),
    Module('access', 'Доступ', 'access', ('view', 'manage', 'assign')),
)

MODULES_BY_NAME = {m.name: m for m in MODULES}
ALL_PERMISSION_NAMES = frozenset(n for m in MODULES for n in m.permission_names())


def assert_known(name):
    """ValueError на невідоме право. Кличеться декоратором при імпорті
    модуля маршрутів, тож друкарська помилка валить застосунок на старті,
    а не мовчки закриває сторінку."""
    if name not in ALL_PERMISSION_NAMES:
        raise ValueError(f'Невідоме право: {name!r}. Додайте його в app/rbac/registry.py')


def module_of(name):
    assert_known(name)
    return MODULES_BY_NAME[name.split('.', 1)[0]]


def action_label(name):
    assert_known(name)
    return ACTIONS[name.split('.', 1)[1]]


def permission_label(name):
    return f'{module_of(name).label}: {action_label(name)}'


def grouped_modules():
    """[(group_key, group_label, [Module, ...]), ...] у порядку GROUPS."""
    return [
        (key, label, [m for m in MODULES if m.group == key])
        for key, label in GROUPS
    ]


# ---------------------------------------------------------------- ролі

SUPER_ADMIN = 'super_admin'

ROLE_COLORS = ('red', 'orange', 'amber', 'green', 'teal', 'blue', 'violet', 'gray')
ROLE_COLOR_LABELS = {
    'red': 'Червоний', 'orange': 'Помаранчевий', 'amber': 'Янтарний',
    'green': 'Зелений', 'teal': 'Бірюзовий', 'blue': 'Синій',
    'violet': 'Фіолетовий', 'gray': 'Сірий',
}


def _expand(*patterns):
    """'courses.*' -> усі права модуля; 'users.view' -> само право."""
    names = set()
    for pattern in patterns:
        module, action = pattern.split('.', 1)
        if action == '*':
            names.update(MODULES_BY_NAME[module].permission_names())
        else:
            assert_known(pattern)
            names.add(pattern)
    return frozenset(names)


def _all_except(*patterns):
    return ALL_PERMISSION_NAMES - _expand(*patterns)


def _views_in(*groups):
    return frozenset(
        f'{m.name}.view' for m in MODULES
        if m.group in groups and 'view' in m.actions
    )


@dataclass(frozen=True)
class RoleSpec:
    name: str
    display_name: str
    description: str
    color: str
    sort_order: int
    defaults: frozenset


ROLES = (
    RoleSpec(SUPER_ADMIN, 'Супер-адміністратор',
             'Повний доступ і керування ролями. Перевірки прав не читає.',
             'red', 0, frozenset()),
    RoleSpec('admin', 'Адміністратор',
             'Усе, крім ролей, системних налаштувань і секретів інтеграцій.',
             'orange', 10,
             _all_except('access.*', 'settings.*', 'integrations.keys',
                         'backup.restore', 'backup.delete')),
    RoleSpec('manager', 'Менеджер',
             'Продажі: реєстрації, замовлення, повернення, сертифікати, заявки.',
             'green', 20,
             _expand('registrations.*', 'online_orders.*', 'certificates.*',
                     'refund_requests.*', 'course_requests.*', 'b2b_requests.*',
                     'promo_codes.view', 'promo_codes.manage', 'promo_codes.export',
                     'referrals.view', 'referrals.export',
                     'meta_leads.view', 'meta_leads.manage', 'meta_leads.export',
                     'cert_generator.*', 'users.view', 'courses.view',
                     'instances.view', 'quizzes.view', 'materials.view',
                     'dashboard.view')),
    RoleSpec('content_editor', 'Редактор контенту',
             'Курси, розклад, тренери, блог, медіа, відгуки, тести, переклади.',
             'blue', 30,
             _expand('courses.*', 'instances.*', 'online_courses.*', 'cities.*',
                     'quizzes.*', 'trainers.*', 'blog.*', 'media.*', 'reviews.*',
                     'translations.*', 'registrations.view', 'dashboard.view')),
    RoleSpec('marketer', 'Маркетолог',
             'Ліди Meta, маркетинг, промокоди, реферали, відгуки.',
             'violet', 40,
             _expand('meta_leads.*', 'marketing.*', 'promo_codes.*', 'referrals.*',
                     'reviews.view', 'reviews.manage', 'users.view', 'courses.view',
                     'instances.view', 'b2b_requests.view', 'course_requests.view',
                     'dashboard.view')),
    RoleSpec('viewer', 'Спостерігач',
             'Лише перегляд, без системних розділів.',
             'gray', 50,
             _views_in('dashboard', 'content', 'sales', 'audience', 'tools')),
)
ROLES_BY_NAME = {r.name: r for r in ROLES}
```

- [ ] **Step 4: Запустити тести**

Run: `python -m pytest tests/test_rbac/test_registry.py -q`
Expected: 10 passed

- [ ] **Step 5: Коміт**

```bash
git add app/rbac/__init__.py app/rbac/registry.py tests/test_rbac/__init__.py tests/test_rbac/test_registry.py
git commit -m "feat(rbac): реєстр прав, груп і дефолтів ролей" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Моделі Role, Permission, UserRole і міграція

**Files:**
- Create: `app/models/rbac.py`, `migrations/versions/rbac_20260905.py`
- Modify: `app/models/__init__.py`, `app/models/user.py`
- Test: `tests/test_rbac/test_models.py`

**Interfaces:**
- Produces: `Role(id, name, display_name, description, color, is_system, sort_order, created_at, permissions: list[Permission])`, `Permission(id, name, module)`, `role_permissions` (Table), `UserRole(user_id, role_id, assigned_at, assigned_by)`, `User.roles` (viewonly), `User.is_staff` (property).
- Колонка `User.is_admin` на цьому кроці ЛИШАЄТЬСЯ (прибирається в Task 8). Міграція поки лише створює таблиці й переносить адмінів; `DROP COLUMN` додається в Task 8 у той самий файл.

- [ ] **Step 1: Тест моделей**

```python
# tests/test_rbac/test_models.py
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
```

- [ ] **Step 2: Запустити, переконатись, що падає**

Run: `python -m pytest tests/test_rbac/test_models.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.models.rbac'`

- [ ] **Step 3: Моделі**

```python
# app/models/rbac.py
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
    users = db.relationship(
        'User', secondary='user_roles', viewonly=True, lazy='select',
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
```

У `app/models/__init__.py` після рядка `from app.models.user import User` додати:

```python
from app.models.rbac import Role, Permission, UserRole
```

і в `__all__` після `'User'` додати `'Role', 'Permission', 'UserRole',`.

У `app/models/user.py` після блоку `medical_profile = db.relationship(...)` додати:

```python
    # Ролі адмін-панелі. viewonly: у user_roles є assigned_at/assigned_by,
    # тож призначення робиться через UserRole (app.rbac.service.assign_roles).
    roles = db.relationship(
        'Role', secondary='user_roles', viewonly=True, lazy='select',
        order_by='Role.sort_order',
    )
```

і після методу `get_referral_code` додати:

```python
    @property
    def is_staff(self):
        """Співробітник = має хоч одну роль. Замінює колишній is_admin там,
        де питання було «чи пускати в адмінку / показувати адмін-лінк»."""
        return bool(self.roles)

    def has_permission(self, name):
        from app.rbac.service import has_permission
        return has_permission(self, name)
```

- [ ] **Step 4: Міграція**

```python
# migrations/versions/rbac_20260905.py
"""RBAC: ролі, права, зв'язки, перенесення is_admin -> super_admin.

Revision ID: rbac_20260905
Revises: email_trigger_transfer_20260831

Створює чотири таблиці, заводить роль super_admin і видає її всім, у кого
стояв is_admin. Решту ролей і всі права створює ``flask rbac sync``
(міграція не імпортує реєстр застосунку). Колонка is_admin прибирається
цим самим файлом у Task 8 плану: до того код ще читає її.
"""
import sqlalchemy as sa
from alembic import op

revision = 'rbac_20260905'
down_revision = 'email_trigger_transfer_20260831'
branch_labels = None
depends_on = None

_BIGPK = sa.BigInteger().with_variant(sa.Integer, 'sqlite')


def upgrade():
    op.create_table(
        'roles',
        sa.Column('id', _BIGPK, primary_key=True),
        sa.Column('name', sa.String(50), nullable=False, unique=True),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('color', sa.String(20), nullable=False, server_default='gray'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('created_at', sa.DateTime(timezone=True)),
    )
    op.create_table(
        'permissions',
        sa.Column('id', _BIGPK, primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('module', sa.String(50), nullable=False),
    )
    op.create_index('ix_permissions_module', 'permissions', ['module'])
    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.BigInteger(),
                  sa.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('permission_id', sa.BigInteger(),
                  sa.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True),
    )
    op.create_table(
        'user_roles',
        sa.Column('user_id', sa.BigInteger(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role_id', sa.BigInteger(),
                  sa.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True)),
        sa.Column('assigned_by', sa.BigInteger(),
                  sa.ForeignKey('users.id', ondelete='SET NULL')),
    )

    conn = op.get_bind()
    roles = sa.table(
        'roles',
        sa.column('id', sa.BigInteger), sa.column('name', sa.String),
        sa.column('display_name', sa.String), sa.column('description', sa.Text),
        sa.column('color', sa.String), sa.column('is_system', sa.Boolean),
        sa.column('sort_order', sa.Integer),
        sa.column('created_at', sa.DateTime(timezone=True)),
    )
    conn.execute(roles.insert().values(
        name='super_admin', display_name='Супер-адміністратор',
        description='Повний доступ і керування ролями. Перевірки прав не читає.',
        color='red', is_system=True, sort_order=0, created_at=sa.func.now(),
    ))
    role_id = conn.execute(
        sa.select(roles.c.id).where(roles.c.name == 'super_admin')
    ).scalar_one()
    conn.execute(sa.text(
        'INSERT INTO user_roles (user_id, role_id, assigned_at) '
        'SELECT id, :rid, CURRENT_TIMESTAMP FROM users WHERE is_admin IS TRUE'
    ), {'rid': role_id})


def downgrade():
    op.drop_table('user_roles')
    op.drop_table('role_permissions')
    op.drop_index('ix_permissions_module', table_name='permissions')
    op.drop_table('permissions')
    op.drop_table('roles')
```

- [ ] **Step 5: Перевірити голову міграцій і тести**

Run: `flask db heads` (очікується один рядок `rbac_20260905`; якщо `down_revision` застарів, взяти актуальну голову з виводу `flask db heads` ДО додавання файла)
Run: `python -m pytest tests/test_rbac -q`
Expected: усі passed

- [ ] **Step 6: Коміт**

```bash
git add app/models/rbac.py app/models/__init__.py app/models/user.py migrations/versions/rbac_20260905.py tests/test_rbac/test_models.py
git commit -m "feat(rbac): моделі Role/Permission/UserRole, зв'язок User.roles, міграція таблиць" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Сервіс перевірок і синк; хелпери тестів

**Files:**
- Create: `app/rbac/service.py`, `tests/support/rbac.py`
- Modify: `tests/conftest.py` (фікстура `app`)
- Test: `tests/test_rbac/test_service.py`, `tests/test_rbac/test_sync.py`

**Interfaces:**
- Produces: `service.effective_permissions(user) -> frozenset[str]`, `service.is_super_admin(user) -> bool`, `service.has_permission(user, name) -> bool`, `service.has_any(user, names) -> bool`, `service.users_with_permission(name) -> list[User]`, `service.sync() -> dict(added, removed, roles_created)`, `service.invalidate_cache()`, `service.AccessError(ValueError)`.
- `tests/support/rbac.py`: `grant_role(user, role_name) -> User`, `make_user_with_role(role_name, email=None, **kwargs) -> User`, `make_super_admin(email=None, **kwargs) -> User`.

- [ ] **Step 1: Тести сервісу**

```python
# tests/test_rbac/test_service.py
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
```

```python
# tests/test_rbac/test_sync.py
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
```

- [ ] **Step 2: Запустити, переконатись, що падає**

Run: `python -m pytest tests/test_rbac/test_service.py tests/test_rbac/test_sync.py -q`
Expected: FAIL з `ImportError` (`app.rbac.service`, `tests.support.rbac`)

- [ ] **Step 3: Сервіс**

```python
# app/rbac/service.py
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
```

- [ ] **Step 4: Хелпери тестів і сідинг у фікстурі `app`**

```python
# tests/support/rbac.py
"""Хелпери RBAC для тестів: користувач із роллю замість колишнього is_admin=True."""
from uuid import uuid4

from app.extensions import db
from app.models.rbac import Role, UserRole
from app.models.user import User


def grant_role(user, role_name):
    role = Role.query.filter_by(name=role_name).one()
    if not any(r.id == role.id for r in user.roles):
        db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.flush()
        db.session.expire(user, ['roles'])
    return user


def make_user_with_role(role_name, email=None, **kwargs):
    kwargs.setdefault('email_confirmed', True)
    user = User.create_with_password(
        email or f'{role_name}-{uuid4().hex[:6]}@test.com', 'password123', **kwargs,
    )
    db.session.flush()
    return grant_role(user, role_name)


def make_super_admin(email=None, **kwargs):
    return make_user_with_role('super_admin', email, **kwargs)
```

У `tests/conftest.py` фікстуру `app` змінити на:

```python
@pytest.fixture(scope='session')
def app():
    """Flask-додаток для тестування. Ролі й права сідяться один раз на сесію:
    без них жоден адмін-маршрут не відкрити."""
    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        from app.rbac import service as rbac_service
        rbac_service.sync()
        _db.session.commit()
        yield app
        _db.drop_all()
```

- [ ] **Step 5: Запустити тести**

Run: `python -m pytest tests/test_rbac -q`
Expected: усі passed

- [ ] **Step 6: Коміт**

```bash
git add app/rbac/service.py tests/support/rbac.py tests/conftest.py tests/test_rbac/test_service.py tests/test_rbac/test_sync.py
git commit -m "feat(rbac): сервіс перевірок, синк реєстру, хелпери тестів" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: CLI `flask rbac` і Jinja-глобали `can` / `can_any`

**Files:**
- Create: `app/rbac/cli.py`
- Modify: `app/rbac/__init__.py`, `app/__init__.py`
- Test: `tests/test_rbac/test_cli.py`

**Interfaces:**
- Produces: `app.rbac.init_app(app)`; Jinja-глобали `can(name)`, `can_any(*names)`; команди `flask rbac sync`, `flask rbac status`.

- [ ] **Step 1: Тест**

```python
# tests/test_rbac/test_cli.py
from app.rbac.cli import rbac_group


def test_rbac_sync_reports_counts(app):
    runner = app.test_cli_runner()
    result = runner.invoke(rbac_group, ['sync'])
    assert result.exit_code == 0, result.output
    assert 'додано прав: 0' in result.output
    assert 'створено ролей: 0' in result.output


def test_rbac_status_lists_roles(app):
    runner = app.test_cli_runner()
    result = runner.invoke(rbac_group, ['status'])
    assert result.exit_code == 0, result.output
    assert 'super_admin' in result.output
    assert 'viewer' in result.output


def test_can_globals_registered(app):
    assert 'can' in app.jinja_env.globals
    assert 'can_any' in app.jinja_env.globals
```

- [ ] **Step 2: Запустити, переконатись, що падає**

Run: `python -m pytest tests/test_rbac/test_cli.py -q`
Expected: FAIL, `ModuleNotFoundError: app.rbac.cli`

- [ ] **Step 3: CLI та init_app**

```python
# app/rbac/cli.py
"""flask rbac sync | status."""
import click
from flask.cli import with_appcontext

from app.extensions import db
from . import registry, service


@click.group('rbac')
def rbac_group():
    """Ролі та права адмін-панелі."""


@rbac_group.command('sync')
@with_appcontext
def rbac_sync():
    """Права з реєстру -> БД; відсутні системні ролі -> створити."""
    result = service.sync()
    db.session.commit()
    click.echo(f"додано прав: {len(result['added'])}"
               + (f" ({', '.join(result['added'])})" if result['added'] else ''))
    click.echo(f"видалено прав: {len(result['removed'])}"
               + (f" ({', '.join(result['removed'])})" if result['removed'] else ''))
    click.echo(f"створено ролей: {len(result['roles_created'])}"
               + (f" ({', '.join(result['roles_created'])})" if result['roles_created'] else ''))


@rbac_group.command('status')
@with_appcontext
def rbac_status():
    """Ролі з кількістю прав і носіїв; розбіжності реєстру й БД."""
    from app.models.rbac import Permission, Role, UserRole
    from sqlalchemy import func

    holders = dict(db.session.query(UserRole.role_id, func.count()).group_by(UserRole.role_id))
    total = len(registry.ALL_PERMISSION_NAMES)
    for role in Role.query.order_by(Role.sort_order, Role.display_name):
        count = total if role.name == registry.SUPER_ADMIN else len(role.permissions)
        click.echo(f'{role.name:<18} {role.display_name:<24} прав {count:>3}/{total}  носіїв {holders.get(role.id, 0)}')
    in_db = {p.name for p in Permission.query.all()}
    missing = sorted(registry.ALL_PERMISSION_NAMES - in_db)
    orphan = sorted(in_db - registry.ALL_PERMISSION_NAMES)
    click.echo(f'немає в БД: {", ".join(missing) or "-"}')
    click.echo(f'немає в реєстрі: {", ".join(orphan) or "-"}')
```

```python
# app/rbac/__init__.py
"""RBAC адмін-панелі.

    from app.rbac import permission_required
    @admin_bp.route('/courses')
    @permission_required('courses.view')
    def courses_list(): ...

Шаблони: {% if can('courses.manage') %} ... {% endif %}
"""
from flask_login import current_user

from . import registry
from .service import has_any, has_permission


def init_app(app):
    app.jinja_env.globals['can'] = lambda name: has_permission(current_user, name)
    app.jinja_env.globals['can_any'] = lambda *names: has_any(current_user, names)
    from .cli import rbac_group
    app.cli.add_command(rbac_group)


__all__ = ['registry', 'has_permission', 'has_any', 'init_app']
```

(Декоратор додасться до `__all__` у Task 5.)

У `app/__init__.py` після рядка `app.cli.add_command(meta_reemit_leads)` додати:

```python
    from app import rbac as _rbac
    _rbac.init_app(app)
```

- [ ] **Step 4: Запустити тести**

Run: `python -m pytest tests/test_rbac -q`
Expected: усі passed

- [ ] **Step 5: Коміт**

```bash
git add app/rbac/cli.py app/rbac/__init__.py app/__init__.py tests/test_rbac/test_cli.py
git commit -m "feat(rbac): команди flask rbac sync/status, Jinja-глобали can/can_any" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

# Етап 2. Захист в'юх

### Task 5: Декоратор `permission_required`, запобіжник блупринта, тест-сторож

**Files:**
- Create: `app/rbac/decorators.py`
- Modify: `app/rbac/__init__.py`, `app/admin/__init__.py`
- Test: `tests/test_rbac/test_decorators.py`, `tests/test_rbac/test_guards.py`

**Interfaces:**
- Produces: `permission_required(*names)` (пропускає за будь-яким із names; ставить на в'юху атрибут `_rbac_permissions: tuple[str]`).
- Тест-сторож `test_every_admin_endpoint_declares_permission` у цій задачі ЧЕРВОНИЙ (усі в'юхи ще під `admin_required`); зеленіє в Task 6. Коміт цієї задачі робиться з червоним сторожем свідомо: він і є списком роботи для Task 6.

- [ ] **Step 1: Тести декоратора**

```python
# tests/test_rbac/test_decorators.py
"""Декоратор перевіряється прямим викликом обгорнутої функції в
test_request_context: реєструвати пробний блупринт на спільному app не
можна (Flask 3 забороняє setup після першого запиту)."""
import pytest
from flask_login import login_user
from werkzeug.exceptions import Forbidden

from app.rbac.decorators import permission_required
from tests.support.rbac import make_super_admin, make_user_with_role

page = permission_required('courses.view')(lambda: 'ok')
either = permission_required('courses.manage', 'blog.view')(lambda: 'ok')


def test_anonymous_redirected_to_login(app):
    with app.test_request_context('/admin/x'):
        resp = page()
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']


def test_viewer_sees_page_but_not_manage(app):
    with app.test_request_context('/admin/x'):
        login_user(make_user_with_role('viewer'))
        assert page() == 'ok'
        with pytest.raises(Forbidden):
            either()


def test_any_of_names_is_enough(app):
    with app.test_request_context('/admin/x'):
        login_user(make_user_with_role('content_editor'))
        assert either() == 'ok'


def test_super_admin_passes_everything(app):
    with app.test_request_context('/admin/x'):
        login_user(make_super_admin())
        assert either() == 'ok'


def test_json_request_gets_json_403(app):
    with app.test_request_context('/admin/access/api/x',
                                  headers={'Accept': 'application/json'}):
        login_user(make_user_with_role('viewer'))
        resp, status = either()
        assert status == 403
        assert resp.get_json() == {'error': 'forbidden'}


def test_json_anonymous_gets_401(app):
    with app.test_request_context('/admin/access/api/x',
                                  headers={'Accept': 'application/json'}):
        resp, status = either()
        assert status == 401


def test_decorator_marks_view_and_rejects_unknown_permission():
    assert either._rbac_permissions == ('courses.manage', 'blog.view')
    with pytest.raises(ValueError):
        permission_required('nope.view')
    with pytest.raises(ValueError):
        permission_required()
```

```python
# tests/test_rbac/test_guards.py
"""Fail-closed: в'юха адмінки без оголошеного права не проходить CI."""
from app.rbac import registry
from tests.support.rbac import make_user_with_role


def test_every_admin_endpoint_declares_permission(app):
    missing = []
    for endpoint, view in app.view_functions.items():
        if not endpoint.startswith('admin.'):
            continue
        names = getattr(view, '_rbac_permissions', None)
        if not names:
            missing.append(endpoint)
            continue
        for name in names:
            assert name in registry.ALL_PERMISSION_NAMES, (endpoint, name)
    assert not missing, 'в\'юхи без @permission_required: ' + ', '.join(sorted(missing))


def test_blueprint_rejects_user_without_roles(app, client):
    from app.extensions import db
    from app.models.user import User
    user = User.create_with_password('norole@test.com', 'password123', email_confirmed=True)
    db.session.flush()
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)
    assert client.get('/admin/courses').status_code == 403


def test_blueprint_redirects_anonymous(client):
    resp = client.get('/admin/courses')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_viewer_reaches_list(app, client):
    with client.session_transaction() as s:
        s['_user_id'] = str(make_user_with_role('viewer').id)
    assert client.get('/admin/courses').status_code == 200
```

- [ ] **Step 2: Запустити, переконатись, що падає**

Run: `python -m pytest tests/test_rbac/test_decorators.py tests/test_rbac/test_guards.py -q`
Expected: FAIL (`ImportError` decorators; сторож червоний)

- [ ] **Step 3: Декоратор і запобіжник**

```python
# app/rbac/decorators.py
"""@permission_required('module.action', ...) -- досить БУДЬ-ЯКОГО з прав.

Анонімного веде на логін (як колишній admin_required), автентифікованого
без права зупиняє 403; запит, що чекає JSON, отримує JSON-тіло.
Атрибут _rbac_permissions читає тест-сторож tests/test_rbac/test_guards.py.
"""
from functools import wraps

from flask import abort, flash, jsonify, redirect, request, url_for
from flask_login import current_user

from . import registry
from .service import has_any

LOGIN_MESSAGE = 'Будь ласка, увійдіть для доступу до цієї сторінки.'


def _wants_json():
    if request.is_json or '/api/' in request.path:
        return True
    return request.accept_mimetypes.best == 'application/json'


def permission_required(*names):
    if not names:
        raise ValueError('permission_required потребує хоч одне право')
    for name in names:
        registry.assert_known(name)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                if _wants_json():
                    return jsonify(error='unauthorized'), 401
                flash(LOGIN_MESSAGE, 'info')
                return redirect(url_for('auth.login'))
            if not has_any(current_user, names):
                if _wants_json():
                    return jsonify(error='forbidden'), 403
                abort(403)
            return view(*args, **kwargs)
        wrapper._rbac_permissions = tuple(names)
        return wrapper
    return decorator
```

У `app/rbac/__init__.py` додати `from .decorators import permission_required` і `'permission_required'` до `__all__`.

У `app/admin/__init__.py` після `admin_bp = Blueprint(...)` додати:

```python
from flask import abort, flash, redirect, url_for
from flask_login import current_user


@admin_bp.before_request
def require_staff():
    """Другий шар поверх @permission_required: у адмінку заходить лише
    носій хоч однієї ролі. В'юха без декоратора (якби сторож вимкнули)
    все одно закрита для сторонніх."""
    if not current_user.is_authenticated:
        flash('Будь ласка, увійдіть для доступу до цієї сторінки.', 'info')
        return redirect(url_for('auth.login'))
    if not current_user.is_staff:
        abort(403)
```

- [ ] **Step 4: Запустити**

Run: `python -m pytest tests/test_rbac/test_decorators.py tests/test_rbac/test_guards.py -q`
Expected: decorators passed; у guards `test_every_admin_endpoint_declares_permission` FAILED зі списком усіх адмін-ендпоінтів, решта passed

- [ ] **Step 5: Коміт**

```bash
git add app/rbac/decorators.py app/rbac/__init__.py app/admin/__init__.py tests/test_rbac/test_decorators.py tests/test_rbac/test_guards.py
git commit -m "feat(rbac): декоратор permission_required, запобіжник блупринта, тест-сторож (червоний до заміни декораторів)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Замінити `admin_required` у 50 файлах маршрутів; перевести 68 тестів на ролі

**Files:**
- Modify: усі `app/admin/routes*.py`
- Delete: `app/admin/decorators.py`
- Modify: 68 тестових файлів (список: `grep -rl "is_admin=True" tests --include=*.py`), `tests/test_models/test_user.py`, `tests/test_db/test_constraints.py`

**Interfaces:**
- Consumes: `from app.rbac import permission_required`.

- [ ] **Step 1: Замінити імпорт у всіх файлах маршрутів**

```bash
grep -rl "from app.admin.decorators import admin_required" app/admin | xargs sed -i 's/from app.admin.decorators import admin_required/from app.rbac import permission_required/'
```

- [ ] **Step 2: Замінити декоратор кожної в'юхи за таблицею**

Кожен `@admin_required` стає `@permission_required('<право>')`. Правило: список і картка (GET) отримують `view`; форма редагування (GET+POST), зміна статусу, службові POST дії отримують `manage`; видалення отримує `delete`; xlsx-звіти й завантаження файлів отримують `export`; імпорт xlsx (upload, preview, apply, cancel) отримує `import`. Винятки перелічені явно.

| Файл | Право за замовчуванням для функцій файла | Винятки (функція -> право) |
|---|---|---|
| routes_analytics | marketing.view | google_analytics_save -> marketing.manage |
| routes_apple_signin | integrations.view | apple_signin_save -> integrations.keys |
| routes_b2b_requests | b2b_requests.view | b2b_requests_export -> b2b_requests.export; b2b_request_update -> b2b_requests.manage |
| routes_backup | backup.view | backup_create, backup_cleanup -> backup.manage; backup_restore -> backup.restore; backup_delete -> backup.delete; backup_download -> backup.export |
| routes_blog | blog.view | blog_create, blog_edit -> blog.manage; blog_delete -> blog.delete |
| routes_blog_comments | blog.view | blog_comment_approve, blog_comment_spam, blog_comment_restore -> blog.manage; blog_comment_delete -> blog.delete |
| routes_certificates | certificates.view | certificates_export -> certificates.export |
| routes_cities | cities.view | cities_save, cities_add, cities_add_missing -> cities.manage; cities_delete -> cities.delete |
| routes_course_requests | course_requests.view | course_requests_export -> course_requests.export; course_request_edit -> course_requests.manage; course_request_delete -> course_requests.delete |
| routes_course_tariffs | courses.manage | course_tariff_delete -> courses.delete; instance_tariffs_sync -> instances.manage |
| routes_courses | courses.view | course_create, course_edit, course_clone -> courses.manage; course_delete -> courses.delete |
| routes_design_system | design_system.view | |
| routes_error_logs | error_logs.view | error_logs_export -> error_logs.export; resolve_error -> error_logs.manage; delete_error_log, error_logs_bulk_action -> error_logs.delete |
| routes_google_oauth | integrations.view | google_oauth_save -> integrations.keys |
| routes_instance_tariffs | instances.manage | instance_tariff_delete -> instances.delete |
| routes_instances | instances.view | instances_report_export -> instances.export; instance_create, instance_edit, instance_lecturer_certificate, instance_status_update -> instances.manage; instance_delete -> instances.delete |
| routes_material_kits | materials.view | material_kit_create, material_kit_edit, material_kit_item_add -> materials.manage; material_kit_delete, material_kit_item_delete -> materials.delete |
| routes_materials | materials.view | materials_overview_export -> materials.export; instance_materials_import -> materials.import; instance_materials_reserve, _update, _edit, _actuals, _adjust, _cancel, _apply_template, materials_reconcile_now -> materials.manage (instance_materials_template і instance_materials_picking лишаються view) |
| routes_media | media.view | media_update_alt, media_restore -> media.manage; media_delete, media_bulk_delete -> media.delete |
| routes_meta_leads | meta_leads.view | meta_leads_export, meta_lead_events_export -> meta_leads.export; meta_lead_detail, meta_lead_form_offer, meta_lead_restore, meta_lead_event_retry -> meta_leads.manage; meta_lead_delete, meta_leads_delete_test -> meta_leads.delete; meta_leads_settings, meta_leads_settings_save, meta_leads_test_mode, meta_leads_check_token, meta_leads_exchange_token, meta_leads_subscribe, meta_leads_reconcile, meta_leads_sync_forms, meta_leads_test_event -> meta_leads.settings |
| routes_meta_pixel | integrations.view | meta_pixel_save -> integrations.keys; meta_pixel_test -> integrations.manage |
| routes_notifications | notifications.view | notifications_log_export -> notifications.export; notifications_settings, notifications_log_resend, notifications_test, scheduler_pause, scheduler_resume -> notifications.manage |
| routes_notifications_recipients | notifications.view | notifications_recipients_save, notifications_recipients_managers_save, notifications_recipients_test -> notifications.manage |
| routes_online_courses | online_courses.view | online_course_edit, online_course_toggle_publish -> online_courses.manage |
| routes_online_orders | online_orders.view | online_orders_export -> online_orders.export; online_order_set_payment, online_order_reissue, online_order_login_link -> online_orders.manage |
| routes_participants | registrations.manage | participants_export -> registrations.export; participants_import_upload, _preview, _apply, _cancel -> registrations.import |
| routes_payments | registrations.view (payments) | liqpay -> integrations.view; liqpay_save_keys -> integrations.keys; liqpay_test, liqpay_reconcile -> integrations.manage |
| routes_perf | perf.view | perf_run_delete, perf_key_rotate, perf_key_clear -> perf.manage |
| routes_posthog | integrations.view | posthog_save -> integrations.keys; posthog_test -> integrations.manage |
| routes_promo_codes | promo_codes.view | promo_codes_export -> promo_codes.export; promo_code_create, promo_code_edit, promo_code_toggle, promo_code_recount -> promo_codes.manage; promo_code_delete -> promo_codes.delete |
| routes_quizzes | quizzes.view | course_quiz_edit, instance_quiz_edit, registration_quiz_unlock, registration_quiz_reset -> quizzes.manage; quiz_delete -> quizzes.delete |
| routes_recaptcha | integrations.view | recaptcha_save_keys -> integrations.keys; recaptcha_test -> integrations.manage |
| routes_referrals | referrals.view | referrals_export -> referrals.export; referrals_reconcile, referral_referrer_adjust -> referrals.manage |
| routes_refund_requests | refund_requests.view | refund_requests_export -> refund_requests.export; refund_request_reject -> refund_requests.manage |
| routes_refunds | registrations.refund | |
| routes_registrations | registrations.view | registrations_export -> registrations.export; registration_status, registration_payment, registration_attendance, registration_completion_link, registration_completion_link_email, registration_transfer -> registrations.manage; registration_certificate_issue, registration_certificate_resend, certificate_revoke -> certificates.manage |
| routes_reviews | reviews.view | review_create, review_edit, review_toggle, review_restore -> reviews.manage; review_delete -> reviews.delete |
| routes_settings | settings.manage | |
| routes_sintegrum | integrations.view | sintegrum_save -> integrations.keys; sintegrum_test, sintegrum_sync -> integrations.manage |
| routes_stubs | integrations.view | dashboard -> dashboard.view; marketing -> marketing.view; integrations_io, integrations_export, integrations_import_preview, integrations_import_apply -> integrations.keys |
| routes_tools | cert_generator.view | tool_certificate_generator_preview, tool_certificate_generator_run -> cert_generator.manage |
| routes_trainers | trainers.view | trainer_create, trainer_edit -> trainers.manage; trainer_delete -> trainers.delete |
| routes_translations | translations.manage | |
| routes_uploads | media.manage | |
| routes_users | users.view | users_export -> users.export; toggle_admin -> access.assign (тимчасово; в'юха видаляється в Task 8) |
| routes_webhooks | webhooks.view | webhook_retry -> webhooks.manage; webhook_delete -> webhooks.delete |
| routes_xlsx | (немає дефолту) | translations_export_object, translations_export -> translations.export; translations_import_upload, _preview, _apply, _cancel -> translations.import; courses_export -> courses.export; courses_import_upload, _preview, _apply, _cancel -> courses.import; instances_export -> instances.export; instances_import_upload, _preview, _apply, _cancel -> instances.import |

Після заміни у файлі не має лишитись жодного `admin_required`:

```bash
grep -rn "admin_required" app/ ; echo "exit=$?"
```

Expected: нічого не знайдено (`exit=1`). Тоді:

```bash
git rm app/admin/decorators.py
```

- [ ] **Step 3: Перевести тести на ролі**

Хелпер уже є (`tests/support/rbac.py`). Замінити в кожному з 68 файлів: у виклику `User.create_with_password(...)` прибрати аргумент `is_admin=True` і після завершення цього виразу додати `grant_role(<змінна>, 'super_admin')` з тим самим відступом, плюс імпорт `from tests.support.rbac import grant_role`. Скрипт для масової заміни (запустити з кореня, у скретч-каталозі, НЕ комітити):

```python
# scratch: migrate_tests.py
import re, sys, pathlib

ROOT = pathlib.Path('tests')
ASSIGN = re.compile(r'^(\s*)(\w+)\s*=\s*User\.create_with_password\(')
IMPORT = 'from tests.support.rbac import grant_role\n'
touched, manual = [], []

for path in ROOT.rglob('*.py'):
    text = path.read_text(encoding='utf-8')
    if 'is_admin=True' not in text:
        continue
    lines = text.splitlines(keepends=True)
    out, i, changed = [], 0, False
    while i < len(lines):
        line = lines[i]
        m = ASSIGN.match(line)
        if m and 'is_admin=True' in ''.join(lines[i:i + 8]):
            indent, var = m.group(1), m.group(2)
            depth, j = 0, i
            while True:
                depth += lines[j].count('(') - lines[j].count(')')
                j += 1
                if depth <= 0:
                    break
            block = ''.join(lines[i:j])
            block = re.sub(r',\s*is_admin=True', '', block)
            block = re.sub(r'is_admin=True,\s*', '', block)
            out.append(block)
            out.append(f"{indent}grant_role({var}, 'super_admin')\n")
            i = j
            changed = True
            continue
        out.append(line)
        i += 1
    new = ''.join(out)
    if 'is_admin=True' in new:
        manual.append(str(path))
    if changed:
        if IMPORT not in new:
            # ПЕРЕД першим import-рядком верхнього рівня: вставка після
            # останнього ламала б багаторядковий `from x import (...)`.
            parts = new.splitlines(keepends=True)
            idx = next(k for k, l in enumerate(parts)
                       if l.startswith(('import ', 'from ')))
            parts.insert(idx, IMPORT)
            new = ''.join(parts)
        path.write_text(new, encoding='utf-8')
        touched.append(str(path))

print('changed:', len(touched))
print('manual:', *manual, sep='\n  ')
```

Run: `python <scratch>/migrate_tests.py`
Expected: `changed: 66` (плюс-мінус), `manual:` містить `tests/test_material_notifications.py`.

Ручні правки:

- `tests/test_material_notifications.py` (2 місця): `User(email=..., is_admin=True)` -> `User(email=...)`, після найближчого `db.session.flush()` (або додати його) вставити `grant_role(<змінна>, 'super_admin')`; додати імпорт хелпера.
- `tests/test_models/test_user.py`: `assert user.is_admin is False` -> `assert user.is_staff is False`.
- `tests/test_db/test_constraints.py:105`: те саме.
- Тести, що перевіряють закриту сторінку як `status_code in (302, 401, 403)`, лишаються чинними.

- [ ] **Step 4: Повний прогін**

Run: `python -m pytest -q`
Expected: усі passed, зокрема `tests/test_rbac/test_guards.py::test_every_admin_endpoint_declares_permission`. Якщо сторож називає ендпоінт, знайти його в таблиці Step 2 і поставити право.

- [ ] **Step 5: Коміт**

```bash
git add -A app/admin app/rbac tests
git commit -m "feat(rbac): усі в'юхи адмінки під permission_required; тести на ролях замість is_admin" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

# Етап 3. Сайдбар, шапка, решта згадок is_admin

### Task 7: Сайдбар під `can`, пункт «Доступ», дашборд веде на доступну сторінку

**Files:**
- Modify: `app/templates/admin/partials/_sidebar.html`, `app/admin/routes_stubs.py`
- Test: `tests/test_rbac/test_sidebar.py`

Пункт «Доступ» веде на `admin.access`, якого ще немає (Task 10). Щоб шаблон рендерився, у цій задачі в `routes_access.py` створюється лише заглушка сторінки; повна версія приходить у Task 10.

- [ ] **Step 1: Тести сайдбару**

```python
# tests/test_rbac/test_sidebar.py
import re
from pathlib import Path

from app.extensions import db
from app.models.rbac import Permission, Role
from tests.support.rbac import make_user_with_role

SIDEBAR = Path('app/templates/admin/partials/_sidebar.html')


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_every_sidebar_link_is_gated():
    text = SIDEBAR.read_text(encoding='utf-8')
    body = text.split('<nav', 1)[1]
    links = re.findall(r"<a href=\"\{\{ url_for\('admin\.\w+'", body)
    gates = re.findall(r'\{% if can(?:_any)?\(', body)
    assert len(links) > 25
    # кожен пункт + кожна група мають свій if
    assert len(gates) >= len(links) + body.count('admin-sidebar__group-title')


def test_sidebar_shows_only_permitted_links(app, client):
    role = Role(name='t_sidebar', display_name='Т')
    role.permissions.append(Permission.query.filter_by(name='courses.view').one())
    role.permissions.append(Permission.query.filter_by(name='dashboard.view').one())
    db.session.add(role)
    db.session.flush()
    _login(client, make_user_with_role('t_sidebar'))

    html = client.get('/admin/courses').get_data(as_text=True)
    assert '/admin/courses' in html
    assert 'Контент' in html
    assert '/admin/users' not in html
    assert 'Продажі' not in html
    assert 'Система' not in html


def test_super_admin_sees_access_link(app, client):
    from tests.support.rbac import make_super_admin
    _login(client, make_super_admin())
    html = client.get('/admin/courses').get_data(as_text=True)
    assert '/admin/access' in html


def test_dashboard_redirects_to_first_visible_page(app, client):
    role = Role(name='t_dash', display_name='Т')
    for name in ('dashboard.view', 'users.view'):
        role.permissions.append(Permission.query.filter_by(name=name).one())
    db.session.add(role)
    db.session.flush()
    _login(client, make_user_with_role('t_dash'))
    resp = client.get('/admin/')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/users')
```

- [ ] **Step 2: Запустити, переконатись, що падає**

Run: `python -m pytest tests/test_rbac/test_sidebar.py -q`
Expected: FAIL

- [ ] **Step 3: Переписати сайдбар**

Кожну групу обгорнути в `{% if can_any(<права всіх пунктів групи>) %} ... {% endif %}`, кожен пункт у `{% if can('<право>') %} ... {% endif %}`. Розмітка самого `<a>` не змінюється. Приклад для групи «Аудиторія» (так само для решти):

```jinja
    {% if can_any('users.view', 'reviews.view') %}
    <div class="admin-sidebar__group">
      <p class="admin-sidebar__group-title">Аудиторія</p>
      {% if can('users.view') %}
      <a href="{{ url_for('admin.users') }}" class="admin-sidebar__link{% if ep == 'admin.users' %} admin-sidebar__link--active{% endif %}">
        {{ icon('group') }}
        <span class="admin-sidebar__text">Користувачі</span>
      </a>
      {% endif %}
      {% if can('reviews.view') %}
      <a href="{{ url_for('admin.reviews_list') }}" class="admin-sidebar__link{% if ep in ('admin.reviews_list', 'admin.review_create', 'admin.review_edit') %} admin-sidebar__link--active{% endif %}">
        {{ icon('reviews') }}
        <span class="admin-sidebar__text">Відгуки</span>
      </a>
      {% endif %}
    </div>
    {% endif %}
```

(Іконки лишити ті, що вже стоять у файлі.) Права пунктів:

| Пункт (endpoint) | Право |
|---|---|
| courses_list | courses.view |
| instances_list | instances.view |
| online_courses_list | online_courses.view |
| cities_list | cities.view |
| quizzes_list | quizzes.view |
| course_requests_list | course_requests.view |
| b2b_requests_list | b2b_requests.view |
| meta_leads_list, meta_lead_forms | meta_leads.view |
| refund_requests_list | refund_requests.view |
| trainers_list | trainers.view |
| blog_list, blog_comments | blog.view |
| media_library | media.view |
| registrations_all | registrations.view |
| online_orders_list | online_orders.view |
| certificates | certificates.view |
| referrals_overview | referrals.view |
| promo_codes_list | promo_codes.view |
| users | users.view |
| reviews_list | reviews.view |
| tool_certificate_generator | cert_generator.view |
| marketing | marketing.view |
| notifications, notifications_recipients | notifications.view |
| integrations | integrations.view |
| webhooks_list | webhooks.view |
| materials_overview, material_kits_list | materials.view |
| error_logs | error_logs.view |
| perf_runs | perf.view |
| design_system | design_system.view |
| settings | settings.manage |
| access (новий) | access.view |

Група «Система» отримує в `can_any` усі свої права, включно з `settings.manage` і `access.view`. У кінці групи «Система», після пункту «Налаштування», додати:

```jinja
      {% if can('access.view') %}
      <a href="{{ url_for('admin.access') }}" class="admin-sidebar__link{% if ep in ('admin.access', 'admin.access_role_new', 'admin.access_role_edit') %} admin-sidebar__link--active{% endif %}">
        {{ icon('group') }}
        <span class="admin-sidebar__text">Доступ</span>
      </a>
      {% endif %}
```

Заглушка сторінки (буде замінена в Task 10):

```python
# app/admin/routes_access.py
"""Сторінка «Доступ»: матриця прав і ролі. Повна версія -- Task 10 плану."""
from flask import render_template

from app.admin import admin_bp
from app.rbac import permission_required


@admin_bp.route('/access')
@permission_required('access.view')
def access():
    return render_template('admin/access.html')
```

Тимчасовий `app/templates/admin/access.html`:

```jinja
{% extends "admin/base_admin.html" %}
{% block title %}Доступ | ІПРМ{% endblock %}
{% block content %}
<div class="admin-with-sidebar">
  {% include 'admin/partials/_sidebar.html' %}
  <div class="admin-layout"><h1 class="admin-hero__title">Доступ</h1></div>
</div>
{% endblock %}
```

Додати `from app.admin import routes_access  # noqa: F401` у `app/admin/routes.py`.

Дашборд у `routes_stubs.py`:

```python
# Куди веде «/admin»: перша сторінка зі списку, яку користувач має право
# бачити. Раніше редирект був на курси, і менеджер без courses.view
# отримував 403 одразу після входу.
_DASHBOARD_TARGETS = (
    ('courses.view', 'admin.courses_list'),
    ('registrations.view', 'admin.registrations_all'),
    ('meta_leads.view', 'admin.meta_leads_list'),
    ('users.view', 'admin.users'),
    ('blog.view', 'admin.blog_list'),
    ('access.view', 'admin.access'),
)


@admin_bp.route('/')
@permission_required('dashboard.view')
def dashboard():
    for permission, endpoint in _DASHBOARD_TARGETS:
        if current_user.has_permission(permission):
            return redirect(url_for(endpoint))
    abort(403)
```

(додати `abort` до імпорту з `flask`).

- [ ] **Step 4: Прогін**

Run: `python -m pytest tests/test_rbac -q && python -m pytest -q`
Expected: усі passed

- [ ] **Step 5: Коміт**

```bash
git add app/templates/admin/partials/_sidebar.html app/admin/routes_stubs.py app/admin/routes_access.py app/admin/routes.py app/templates/admin/access.html tests/test_rbac/test_sidebar.py
git commit -m "feat(rbac): сайдбар за правами, пункт «Доступ», дашборд веде на доступну сторінку" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Прибрати `is_admin` з коду й БД

**Files:**
- Modify: `app/models/user.py`, `migrations/versions/rbac_20260905.py`, `app/templates/partials/header.html`, `app/templates/partials/_posthog.html`, `app/services/notification_recipients.py`, `app/templates/admin/notifications_recipients.html`, `app/services/xlsx_reports.py`, `app/admin/routes_meta_leads.py`, `app/models/material_reservation.py`, `app/templates/admin/users.html`, `app/templates/admin/user_detail.html`, `app/admin/routes_users.py`
- Test: `tests/test_rbac/test_is_admin_removed.py`

Список користувачів і картка тут лише позбавляються `is_admin` (бейджі ролей і форма призначення приходять у Task 12).

- [ ] **Step 1: Тест**

```python
# tests/test_rbac/test_is_admin_removed.py
import re
from pathlib import Path

from app.models.user import User
from app.rbac import service
from tests.support.rbac import make_super_admin, make_user_with_role


def test_no_is_admin_left_in_app():
    hits = []
    for path in Path('app').rglob('*'):
        if path.suffix not in ('.py', '.html') or 'migrations' in path.parts:
            continue
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if re.search(r'\bis_admin\b', line):
                hits.append(f'{path}:{n}')
    assert not hits, hits


def test_user_has_no_is_admin_column():
    assert not hasattr(User, 'is_admin')


def test_admin_alert_recipients_come_from_permission(app):
    from app.models.notification_rule import NotificationRule
    from app.services import notification_recipients
    with app.test_request_context():
        sa = make_super_admin()
        viewer = make_user_with_role('viewer')
        rule = NotificationRule.query.first()
        if rule is None:
            return  # правила сідяться окремим сідером; тоді перевіряє test_service
        rule.enabled = True
        rule.notify_admins = True
        emails = notification_recipients.resolve(rule.event_type)
        assert sa.email in emails
        assert viewer.email not in emails
```

- [ ] **Step 2: Запустити, переконатись, що падає**

Run: `python -m pytest tests/test_rbac/test_is_admin_removed.py -q`
Expected: FAIL зі списком згадок

- [ ] **Step 3: Правки**

`app/models/user.py`: видалити рядок `is_admin = db.Column(db.Boolean, default=False)`.

`migrations/versions/rbac_20260905.py`: у кінець `upgrade()` додати

```python
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_admin')
```

а на початок `downgrade()`:

```python
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_admin', sa.Boolean(), server_default=sa.false()))
    op.execute(sa.text(
        "UPDATE users SET is_admin = TRUE WHERE id IN ("
        "SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
        "WHERE r.name = 'super_admin')"
    ))
```

`partials/header.html` (2 місця): `current_user.is_admin` -> `current_user.is_staff`.

`partials/_posthog.html`: `data-ph-role="{{ 'staff' if current_user.is_staff else 'user' }}"`.

`app/services/notification_recipients.py`: докстрінг `notify_admins -> усі активні користувачі з правом notifications.receive (super_admin включно)`; у `resolve`:

```python
    if rule.notify_admins:
        from app.rbac.service import users_with_permission
        admins = users_with_permission('notifications.receive')
        breakdown['admins'] = [u.email for u in admins if u.email]
```

`notifications_recipients.html`: підпис `Адміністратори (User.is_admin)` -> `Носії права «Сповіщення: Службові листи» (матриця доступу)`.

`app/services/xlsx_reports.py`: у `_USER_COLS`, `_USER_LABELS`, `_USER_WIDTHS` ключ `is_admin` -> `roles` з підписом `'Ролі'` і шириною `24`; у рядку замість `'Так' if user.is_admin else 'Ні'` -> `', '.join(r.display_name for r in user.roles)`.

`app/admin/routes_meta_leads.py`: рядок 716 `if user.is_admin:` -> `if user.is_staff:` з текстом `'має роль в адмінці'`; рядок 771-774: коментар `# Носіїв ролей відсіваємо в тому ж запиті.` і фільтр `User.is_admin.is_(False)` -> `~User.roles.any()`.

`app/models/material_reservation.py`: коментар `IPRM has no role system, so this is the only accountability trail available` -> `Who filed the request in the IPRM admin; kept alongside RBAC roles as the accountability trail`.

`users.html`: прибрати блок `{% if user.is_admin %}<span class="badge badge--active">admin</span>{% endif %}` і всю форму `toggle_admin` у колонці «Дії» (замінити вміст `<td>` на `<a href="{{ url_for('admin.user_detail', user_id=user.id) }}" class="btn-admin btn-admin--secondary btn-admin--sm">Картка</a>`).

`user_detail.html`: прибрати `{% if user.is_admin %}<span class="badge badge--active">адміністратор</span>{% endif %}`.

`routes_users.py`: видалити в'юху `toggle_admin`; у `_USER_ROLES`, `_user_filters`, `_users_query`, `users_export` фільтр «Роль» перевести на ролі:

```python
def _role_choices():
    """Фільтр «Роль»: реальні ролі + «без ролей». Рахується на запит, бо ролі
    редагуються в адмінці."""
    from app.models.rbac import Role
    choices = {'none': 'Без ролей'}
    for role in Role.query.order_by(Role.sort_order, Role.display_name):
        choices[role.name] = role.display_name
    return choices
```

У `_user_filters`: `'role': _listing.choice_arg('role', _role_choices())`. У `_users_query`:

```python
    if filters['role'] == 'none':
        query = query.filter(~User.roles.any())
    elif filters['role']:
        from app.models.rbac import Role
        query = query.filter(User.roles.any(Role.name == filters['role']))
```

і до `.options(joinedload(User.medical_profile))` додати `.options(selectinload(User.roles))` (імпорт `selectinload` з `sqlalchemy.orm`). У `users()` `role_options=list(_role_choices().items())`; в `users_export` `('Роль', _role_choices().get(filters['role'], 'Усі'))`. Константу `_USER_ROLES` видалити.

- [ ] **Step 4: Повний прогін**

Run: `python -m pytest -q`
Expected: усі passed. `tests/test_routes/test_admin_users_filters.py`: якщо він фільтрував `role=admin`, замінити на `role=super_admin`.

- [ ] **Step 5: Коміт**

```bash
git add -A app migrations tests
git commit -m "feat(rbac): прибрати is_admin: колонку, шапку, одержувачів листів, звіт, фільтр користувачів" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

# Етап 4. Сторінка «Доступ»

### Task 9: Операції над ролями з запобіжниками (сервіс)

**Files:**
- Modify: `app/rbac/service.py`
- Test: `tests/test_rbac/test_role_ops.py`

**Interfaces:**
- Produces: `set_role_permission(role, name, granted, actor) -> None`, `set_module_permissions(role, module_name, granted, actor) -> list[str]` (імена прав модуля, що лишились у ролі), `reset_role_to_defaults(role, actor)`, `create_role(name, display_name, description, color, sort_order, actor, copy_from=None) -> Role`, `update_role(role, display_name, description, color, sort_order, actor, name=None)`, `delete_role(role, actor)`, `assign_roles(user, role_ids: set[int], actor)`, `holders_count(role) -> int`. Усі кидають `AccessError`, не комітять.

- [ ] **Step 1: Тести**

```python
# tests/test_rbac/test_role_ops.py
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
```

- [ ] **Step 2: Запустити, переконатись, що падає**

Run: `python -m pytest tests/test_rbac/test_role_ops.py -q`
Expected: FAIL, `AttributeError: module 'app.rbac.service' has no attribute 'create_role'`

- [ ] **Step 3: Реалізація (додати в кінець `app/rbac/service.py`)**

```python
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
    import re
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
    if name and name != role.name:
        if role.is_system:
            raise AccessError('Код системної ролі не змінюється')
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
```

- [ ] **Step 4: Прогін**

Run: `python -m pytest tests/test_rbac -q`
Expected: усі passed

- [ ] **Step 5: Коміт**

```bash
git add app/rbac/service.py tests/test_rbac/test_role_ops.py
git commit -m "feat(rbac): операції над ролями й призначенням із запобіжниками" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Компоненти дизайн-системи: перемикач, крапка й бейдж ролі, палітра

**Files:**
- Modify: `app/static/css/common.css`, `app/static/css/admin.css`, `app/templates/design_system/_tab_admin.html`

- [ ] **Step 1: Токени палітри в `common.css`**

У блок `:root` (світла тема) додати після токенів бейджів:

```css
  /* Палітра ролей адмінки. Роль зберігає ІМ'Я кольору, клас
     .role-color--<name> перекладає його в --role-color. */
  --iprm-role-red: #dc2626;
  --iprm-role-orange: #ea580c;
  --iprm-role-amber: #d97706;
  --iprm-role-green: #059669;
  --iprm-role-teal: #0d9488;
  --iprm-role-blue: #2563eb;
  --iprm-role-violet: #7c3aed;
  --iprm-role-gray: #6b7280;
```

У блок `[data-theme="dark"]` додати світліші варіанти:

```css
  --iprm-role-red: #f87171;
  --iprm-role-orange: #fb923c;
  --iprm-role-amber: #fbbf24;
  --iprm-role-green: #34d399;
  --iprm-role-teal: #2dd4bf;
  --iprm-role-blue: #60a5fa;
  --iprm-role-violet: #a78bfa;
  --iprm-role-gray: #9ca3af;
```

Після правил `.badge--*` у `common.css` додати:

```css
/* Колір ролі: клас-перекладач імені з палітри в --role-color. Один набір
   для бейджа, крапки та зразка в формі ролі. */
.role-color--red { --role-color: var(--iprm-role-red); }
.role-color--orange { --role-color: var(--iprm-role-orange); }
.role-color--amber { --role-color: var(--iprm-role-amber); }
.role-color--green { --role-color: var(--iprm-role-green); }
.role-color--teal { --role-color: var(--iprm-role-teal); }
.role-color--blue { --role-color: var(--iprm-role-blue); }
.role-color--violet { --role-color: var(--iprm-role-violet); }
.role-color--gray { --role-color: var(--iprm-role-gray); }

.badge--role {
  color: var(--role-color, var(--iprm-role-gray));
  background: color-mix(in srgb, var(--role-color, var(--iprm-role-gray)) 14%, transparent);
}
```

- [ ] **Step 2: Компоненти в `admin.css`** (у кінець файла)

```css
/* ========== РОЛІ ТА ДОСТУП ========== */

/* Крапка кольору ролі: у шапці матриці, у списку ролей, біля бейджа. */
.role-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--role-color, var(--iprm-role-gray));
  vertical-align: middle;
  flex-shrink: 0;
}

/* Перемикач (switch). Прихований чекбокс + доріжка з бігунком; стан
   задає :checked, замок -- :disabled. */
.switch {
  position: relative;
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}

.switch__input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.switch__track {
  position: relative;
  width: 34px;
  height: 20px;
  border-radius: var(--iprm-radius-pill);
  background: var(--iprm-border-strong);
  transition: background var(--iprm-transition);
}

.switch__knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--iprm-white);
  box-shadow: var(--iprm-shadow-xs);
  transition: transform var(--iprm-transition);
}

.switch__input:checked + .switch__track {
  background: var(--iprm-success);
}

.switch__input:checked + .switch__track .switch__knob {
  transform: translateX(14px);
}

.switch__input:disabled + .switch__track {
  opacity: 0.5;
  cursor: not-allowed;
}

.switch__input:focus-visible + .switch__track {
  outline: 2px solid var(--iprm-nav-active);
  outline-offset: 2px;
}

/* Зразок кольору в формі ролі: радіокнопка з крапкою й підписом. */
.role-swatch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--iprm-border);
  border-radius: var(--iprm-radius-pill);
  cursor: pointer;
  font-size: 0.8125rem;
}

.role-swatch input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.role-swatch:has(input:checked) {
  border-color: var(--role-color);
  box-shadow: 0 0 0 1px var(--role-color);
}
```

- [ ] **Step 3: Показати в каталозі**

У `app/templates/design_system/_tab_admin.html` перед закривальним `</div>` секції `#admin` додати:

```jinja
    <h3 class="ds-section-heading">Ролі та доступ</h3>
    <div class="ds-demo">
      <div class="ds-row">
        <span class="badge badge--role role-color--red"><span class="role-dot"></span> Супер-адміністратор</span>
        <span class="badge badge--role role-color--orange"><span class="role-dot"></span> Адміністратор</span>
        <span class="badge badge--role role-color--green"><span class="role-dot"></span> Менеджер</span>
        <span class="badge badge--role role-color--blue"><span class="role-dot"></span> Редактор</span>
        <span class="badge badge--role role-color--violet"><span class="role-dot"></span> Маркетолог</span>
        <span class="badge badge--role role-color--gray"><span class="role-dot"></span> Спостерігач</span>
      </div>
      <div class="ds-row">
        <span class="role-dot role-color--amber"></span>
        <span class="role-dot role-color--teal"></span>
        <label class="switch"><input type="checkbox" class="switch__input" checked aria-label="Увімкнено"><span class="switch__track"><span class="switch__knob"></span></span></label>
        <label class="switch"><input type="checkbox" class="switch__input" aria-label="Вимкнено"><span class="switch__track"><span class="switch__knob"></span></span></label>
        <label class="switch"><input type="checkbox" class="switch__input" checked disabled aria-label="Заблоковано"><span class="switch__track"><span class="switch__knob"></span></span></label>
        <label class="role-swatch role-color--violet"><input type="radio" name="ds-swatch" checked><span class="role-dot"></span> Фіолетовий</label>
        <label class="role-swatch role-color--teal"><input type="radio" name="ds-swatch"><span class="role-dot"></span> Бірюзовий</label>
      </div>
    </div>
    <p class="ds-hint">.role-color--&lt;name&gt; перекладає ім'я з палітри (red orange amber green teal blue violet gray, токени --iprm-role-*) у --role-color; його читають .badge--role, .role-dot і .role-swatch. .switch: прихований чекбокс + доріжка; :checked фарбує в --iprm-success, :disabled ставить замок (колонка super_admin у матриці /admin/access).</p>
```

- [ ] **Step 4: Сторожі дизайн-системи**

Run: `python -m pytest tests/test_design_system -q && python tools/ds/ds_audit.py`
Expected: passed; аудит не показує нових дублікатів

- [ ] **Step 5: Коміт**

```bash
git add app/static/css/common.css app/static/css/admin.css app/templates/design_system/_tab_admin.html
git commit -m "feat(ds): перемикач, крапка й бейдж ролі, палітра кольорів ролей" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Сторінка матриці, JSON API, JS автозбереження

**Files:**
- Modify: `app/admin/routes_access.py`, `app/templates/admin/access.html`
- Create: `app/static/js/admin-access-matrix.js`, `app/static/css/page-admin-access.css`
- Test: `tests/test_rbac/test_access_routes.py`

**Interfaces:**
- Produces: `GET /admin/access` (access.view), `PUT /admin/access/api/matrix` (access.manage; JSON `{role_id, permission, granted}` -> `{ok, role_id, role_count}`), `POST /admin/access/api/matrix/bulk` (access.manage; `{role_id, module, mode}` -> `{ok, role_id, module, granted: [...], role_count}`).
- Ендпоінти `admin.access_role_new`, `admin.access_role_edit`, `admin.access_role_delete`, `admin.access_role_reset` з'являються в Task 12; у шаблоні цієї задачі посилання на них ставляться одразу, тому тести цієї задачі запускати після додавання заглушок цих маршрутів (Step 3 містить їх).

- [ ] **Step 1: Тести**

```python
# tests/test_rbac/test_access_routes.py
from app.extensions import db
from app.models.rbac import Role
from app.rbac import registry
from tests.support.rbac import make_super_admin, make_user_with_role


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _viewer_with(*perms):
    role = Role(name='t_access_' + '_'.join(p.replace('.', '') for p in perms), display_name='T')
    from app.models.rbac import Permission
    for p in perms:
        role.permissions.append(Permission.query.filter_by(name=p).one())
    db.session.add(role)
    db.session.flush()
    return make_user_with_role(role.name)


def test_matrix_page_renders_all_permissions_and_roles(client):
    _login(client, make_super_admin())
    html = client.get('/admin/access').get_data(as_text=True)
    assert 'Матриця прав' in html
    for name in ('courses.view', 'access.assign', 'registrations.refund'):
        assert f'data-permission="{name}"' in html
    for role in ('Супер-адміністратор', 'Менеджер', 'Спостерігач'):
        assert role in html
    assert html.count('data-group-toggle=') == len(registry.GROUPS)


def test_matrix_readonly_for_access_view_only(client):
    _login(client, _viewer_with('access.view'))
    html = client.get('/admin/access').get_data(as_text=True)
    assert 'data-readonly="1"' in html
    assert 'data-bulk=' not in html


def test_toggle_permission_via_api(client):
    _login(client, make_super_admin())
    role = Role.query.filter_by(name='viewer').one()
    before = len(role.permissions)
    resp = client.put('/admin/access/api/matrix', json={
        'role_id': role.id, 'permission': 'courses.manage', 'granted': True})
    assert resp.status_code == 200
    assert resp.get_json()['role_count'] == before + 1
    resp = client.put('/admin/access/api/matrix', json={
        'role_id': role.id, 'permission': 'courses.manage', 'granted': False})
    assert resp.get_json()['role_count'] == before


def test_toggle_super_admin_is_400(client):
    _login(client, make_super_admin())
    sa = Role.query.filter_by(name='super_admin').one()
    resp = client.put('/admin/access/api/matrix', json={
        'role_id': sa.id, 'permission': 'courses.view', 'granted': False})
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_bulk_module(client):
    _login(client, make_super_admin())
    role = Role.query.filter_by(name='viewer').one()
    resp = client.post('/admin/access/api/matrix/bulk', json={
        'role_id': role.id, 'module': 'blog', 'mode': 'all'})
    assert resp.status_code == 200
    assert set(resp.get_json()['granted']) == {'blog.view', 'blog.manage', 'blog.delete'}
    resp = client.post('/admin/access/api/matrix/bulk', json={
        'role_id': role.id, 'module': 'blog', 'mode': 'none'})
    assert resp.get_json()['granted'] == []
    # повернути дефолт viewer
    client.put('/admin/access/api/matrix', json={
        'role_id': role.id, 'permission': 'blog.view', 'granted': True})


def test_api_forbidden_without_manage(client):
    _login(client, _viewer_with('access.view'))
    role = Role.query.filter_by(name='viewer').one()
    resp = client.put('/admin/access/api/matrix', json={
        'role_id': role.id, 'permission': 'courses.manage', 'granted': True})
    assert resp.status_code == 403
    assert resp.get_json() == {'error': 'forbidden'}


def test_unknown_role_is_404(client):
    _login(client, make_super_admin())
    resp = client.put('/admin/access/api/matrix', json={
        'role_id': 999999, 'permission': 'courses.view', 'granted': True})
    assert resp.status_code == 404
```

- [ ] **Step 2: Запустити, переконатись, що падає**

Run: `python -m pytest tests/test_rbac/test_access_routes.py -q`
Expected: FAIL (404 на API, немає «Матриця прав»)

- [ ] **Step 3: Маршрути**

Замінити вміст `app/admin/routes_access.py`:

```python
"""Сторінка «Доступ»: матриця прав і ролі.

Рядки матриці приходять із реєстру (app/rbac/registry.py), стан
перемикачів -- із role_permissions. Збереження -- JSON API після кожного
кліку (admin-access-matrix.js). CRUD ролей -- серверні форми (Task 12).
"""
import logging

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.admin import admin_bp
from app.extensions import db
from app.models.rbac import Role, UserRole
from app.rbac import permission_required, registry, service
from app.rbac.service import AccessError

audit_logger = logging.getLogger('audit')


def _roles_ordered():
    return (Role.query.options(selectinload(Role.permissions))
            .order_by(Role.sort_order, Role.display_name).all())


def _role_count(role, total):
    return total if role.name == registry.SUPER_ADMIN else len(role.permissions)


@admin_bp.route('/access')
@permission_required('access.view')
def access():
    roles = _roles_ordered()
    total = len(registry.ALL_PERMISSION_NAMES)
    granted = {r.id: {p.name for p in r.permissions} for r in roles}
    counts = {r.id: _role_count(r, total) for r in roles}
    holders = dict(db.session.query(UserRole.role_id, func.count())
                   .group_by(UserRole.role_id))
    groups = []
    for key, label, modules in registry.grouped_modules():
        groups.append({
            'key': key, 'label': label,
            'total': sum(len(m.actions) for m in modules),
            'modules': [{
                'name': m.name, 'label': m.label,
                'permissions': [{'name': n, 'label': registry.action_label(n)}
                                for n in m.permission_names()],
            } for m in modules],
        })
    return render_template(
        'admin/access.html',
        roles=roles, granted=granted, counts=counts, total=total,
        holders=holders, groups=groups,
        super_admin=registry.SUPER_ADMIN,
        can_manage=current_user.has_permission('access.manage'),
    )


def _json_role():
    data = request.get_json(silent=True) or {}
    role_id = data.get('role_id')
    if not isinstance(role_id, int):
        abort(400)
    role = db.session.get(Role, role_id)
    if role is None:
        abort(404)
    return role, data


@admin_bp.route('/access/api/matrix', methods=['PUT'])
@permission_required('access.manage')
def access_matrix_toggle():
    role, data = _json_role()
    try:
        service.set_role_permission(
            role, str(data.get('permission', '')), bool(data.get('granted')), current_user)
        db.session.commit()
    except AccessError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, role_id=role.id,
                   role_count=_role_count(role, len(registry.ALL_PERMISSION_NAMES)))


@admin_bp.route('/access/api/matrix/bulk', methods=['POST'])
@permission_required('access.manage')
def access_matrix_bulk():
    role, data = _json_role()
    mode = data.get('mode')
    if mode not in ('all', 'none'):
        return jsonify(error='mode має бути all або none'), 400
    try:
        granted = service.set_module_permissions(
            role, str(data.get('module', '')), mode == 'all', current_user)
        db.session.commit()
    except AccessError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, role_id=role.id, module=data.get('module'),
                   granted=granted,
                   role_count=_role_count(role, len(registry.ALL_PERMISSION_NAMES)))


# Заглушки CRUD ролей: повна реалізація в Task 12. Потрібні вже тут, бо
# шаблон матриці посилається на них.
@admin_bp.route('/access/roles/new', methods=['GET', 'POST'])
@permission_required('access.manage')
def access_role_new():
    abort(404)


@admin_bp.route('/access/roles/<int:role_id>/edit', methods=['GET', 'POST'])
@permission_required('access.manage')
def access_role_edit(role_id):
    abort(404)


@admin_bp.route('/access/roles/<int:role_id>/delete', methods=['POST'])
@permission_required('access.manage')
def access_role_delete(role_id):
    abort(404)


@admin_bp.route('/access/roles/<int:role_id>/reset', methods=['POST'])
@permission_required('access.manage')
def access_role_reset(role_id):
    abort(404)
```

- [ ] **Step 4: Шаблон `admin/access.html`**

```jinja
{% extends "admin/base_admin.html" %}

{% block title %}Доступ | ІПРМ{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/admin.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-admin-access.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="admin-with-sidebar">
  {% include 'admin/partials/_sidebar.html' %}
  <div class="admin-layout admin-layout--wide">
    <div class="admin-hero">
      <div>
        <div class="admin-breadcrumb">
          <a href="{{ url_for('admin.dashboard') }}" class="admin-breadcrumb__link">Панель</a>
          <span class="admin-breadcrumb__sep">/</span>
          <span class="admin-breadcrumb__current">Доступ</span>
        </div>
        <h1 class="admin-hero__title">Матриця прав</h1>
        <p class="admin-hero__subtitle">{{ total }} прав, {{ roles|length }} ролей. Зміни зберігаються одразу після кліку.</p>
      </div>
      {% if can_manage %}
      <a href="{{ url_for('admin.access_role_new') }}" class="btn-admin btn-admin--primary">{{ icon('add') }} Нова роль</a>
      {% endif %}
    </div>

    {% include 'partials/flash_messages.html' %}

    <div class="access-layout">
      <section class="access-matrix" id="access-matrix"
               data-api-toggle="{{ url_for('admin.access_matrix_toggle') }}"
               data-api-bulk="{{ url_for('admin.access_matrix_bulk') }}"
               data-csrf="{{ csrf_token() }}"
               data-readonly="{{ '0' if can_manage else '1' }}">
        <div class="access-toolbar">
          <input type="search" id="access-search" class="form-control access-toolbar__search"
                 placeholder="Пошук права або модуля" aria-label="Пошук права">
          <span class="access-status" id="access-status" role="status" aria-live="polite">
            {% if can_manage %}Готово{% else %}Лише перегляд: потрібне право «Доступ: Керування»{% endif %}
          </span>
        </div>

        <div class="admin-table-wrap access-matrix__scroll">
          <table class="admin-table access-matrix__table">
            <thead>
              <tr>
                <th class="access-matrix__label">Право</th>
                {% for role in roles %}
                <th class="access-matrix__role role-color--{{ role.color }}">
                  <span class="role-dot"></span>
                  <span class="access-matrix__role-name">{{ role.display_name }}</span>
                  <span class="access-matrix__count" data-role-count="{{ role.id }}" data-total="{{ total }}">{{ counts[role.id] }} з {{ total }}</span>
                </th>
                {% endfor %}
              </tr>
            </thead>
            {% for group in groups %}
            <tbody class="access-group" data-group="{{ group.key }}">
              <tr class="access-group__head">
                <th colspan="{{ roles|length + 1 }}">
                  <button type="button" class="access-group__toggle" data-group-toggle="{{ group.key }}" aria-expanded="true">
                    {{ icon('keyboard_arrow_down', cls='access-group__chevron') }}
                    {{ group.label }}
                    <span class="access-matrix__count">{{ group.total }}</span>
                  </button>
                </th>
              </tr>
              {% for module in group.modules %}
              <tr class="access-module" data-module="{{ module.name }}">
                <th class="access-module__title">{{ module.label }}</th>
                {% for role in roles %}
                <td class="access-module__bulk">
                  {% if can_manage and role.name != super_admin %}
                  <button type="button" class="btn-admin btn-admin--secondary btn-admin--sm" data-bulk="all" data-role-id="{{ role.id }}" data-module="{{ module.name }}" title="Усі права модуля для ролі {{ role.display_name }}">усе</button>
                  <button type="button" class="btn-admin btn-admin--secondary btn-admin--sm" data-bulk="none" data-role-id="{{ role.id }}" data-module="{{ module.name }}" title="Зняти всі права модуля з ролі {{ role.display_name }}">нічого</button>
                  {% endif %}
                </td>
                {% endfor %}
              </tr>
              {% for perm in module.permissions %}
              <tr class="access-perm" data-permission-row="{{ perm.name }}" data-search="{{ (module.label ~ ' ' ~ perm.label ~ ' ' ~ perm.name)|lower }}">
                <td class="access-perm__label">
                  <span>{{ perm.label }}</span>
                  <span class="access-perm__code">{{ perm.name }}</span>
                </td>
                {% for role in roles %}
                <td class="access-perm__cell">
                  <label class="switch">
                    <input type="checkbox" class="switch__input"
                           data-role-id="{{ role.id }}" data-permission="{{ perm.name }}" data-module="{{ module.name }}"
                           aria-label="{{ module.label }}: {{ perm.label }} для ролі {{ role.display_name }}"
                           {% if role.name == super_admin or perm.name in granted[role.id] %} checked{% endif %}
                           {% if role.name == super_admin or not can_manage %} disabled{% endif %}>
                    <span class="switch__track"><span class="switch__knob"></span></span>
                  </label>
                </td>
                {% endfor %}
              </tr>
              {% endfor %}
              {% endfor %}
            </tbody>
            {% endfor %}
          </table>
        </div>
      </section>

      <aside class="access-roles">
        <h2 class="access-roles__title">Ролі</h2>
        {% for role in roles %}
        <article class="access-role role-color--{{ role.color }}">
          <header class="access-role__head">
            <span class="role-dot"></span>
            <strong>{{ role.display_name }}</strong>
            <span class="access-role__slug">{{ role.name }}</span>
          </header>
          {% if role.description %}<p class="access-role__desc">{{ role.description }}</p>{% endif %}
          <p class="access-role__meta">{{ counts[role.id] }} прав, {{ holders.get(role.id, 0) }} носіїв{% if role.is_system %}, системна{% endif %}</p>
          {% if can_manage %}
          <div class="access-role__actions">
            <a href="{{ url_for('admin.access_role_edit', role_id=role.id) }}" class="btn-admin btn-admin--secondary btn-admin--sm">Редагувати</a>
            {% if role.is_system and role.name != super_admin %}
            <form method="POST" action="{{ url_for('admin.access_role_reset', role_id=role.id) }}" data-confirm="Повернути права ролі «{{ role.display_name }}» до дефолтів з коду?" data-confirm-ok="Скинути">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
              <button type="submit" class="btn-admin btn-admin--secondary btn-admin--sm">Скинути</button>
            </form>
            {% endif %}
            {% if not role.is_system %}
            <form method="POST" action="{{ url_for('admin.access_role_delete', role_id=role.id) }}" data-confirm="Видалити роль «{{ role.display_name }}»?" data-confirm-ok="Видалити">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
              <button type="submit" class="btn-admin btn-admin--danger btn-admin--sm">Видалити</button>
            </form>
            {% endif %}
          </div>
          {% endif %}
        </article>
        {% endfor %}
      </aside>
    </div>
  </div>
</div>
{% endblock %}

{% block extra_scripts %}
{{ super() }}
<script src="{{ url_for('static', filename='js/admin-access-matrix.js') }}?v={{ assets_version }}" defer></script>
{% endblock %}
```

- [ ] **Step 5: JS**

```js
/* admin-access-matrix.js -- матриця прав /admin/access.

   Перемикач шле PUT одразу після кліку; при помилці повертає стан і
   пише в рядок стану. Кнопки «усе/нічого» шлють POST на модуль і
   виставляють перемикачі модуля за відповіддю. Групи згортаються,
   стан пам'ятається в localStorage. Пошук фільтрує рядки прав. */
(function () {
  'use strict';

  var root = document.getElementById('access-matrix');
  if (!root) return;

  var status = document.getElementById('access-status');
  var search = document.getElementById('access-search');
  var csrf = root.getAttribute('data-csrf') || '';
  var readonly = root.getAttribute('data-readonly') === '1';
  var STORAGE_KEY = 'admin-access-collapsed';

  function setStatus(text, state) {
    if (!status) return;
    status.textContent = text;
    status.setAttribute('data-state', state || '');
  }

  function send(url, method, payload) {
    return fetch(url, {
      method: method,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-CSRFToken': csrf,
        'X-Requested-With': 'XMLHttpRequest'
      },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
        return data;
      });
    });
  }

  function updateCount(roleId, count) {
    var el = root.querySelector('[data-role-count="' + roleId + '"]');
    if (el) el.textContent = count + ' з ' + el.getAttribute('data-total');
  }

  /* ---- перемикачі ---- */
  root.addEventListener('change', function (e) {
    var input = e.target;
    if (readonly || !input.classList.contains('switch__input')) return;
    var granted = input.checked;
    input.disabled = true;
    setStatus('Зберігаю...', 'busy');
    send(root.getAttribute('data-api-toggle'), 'PUT', {
      role_id: Number(input.getAttribute('data-role-id')),
      permission: input.getAttribute('data-permission'),
      granted: granted
    }).then(function (data) {
      updateCount(data.role_id, data.role_count);
      setStatus('Збережено', 'ok');
    }).catch(function (err) {
      input.checked = !granted;
      setStatus('Помилка, зміну скасовано: ' + err.message, 'error');
    }).then(function () {
      input.disabled = false;
    });
  });

  /* ---- гуртові дії й згортання груп ---- */
  root.addEventListener('click', function (e) {
    var bulk = e.target.closest('[data-bulk]');
    if (bulk && !readonly) {
      var roleId = Number(bulk.getAttribute('data-role-id'));
      var module = bulk.getAttribute('data-module');
      var buttons = root.querySelectorAll('[data-bulk][data-role-id="' + roleId + '"][data-module="' + module + '"]');
      buttons.forEach(function (b) { b.disabled = true; });
      setStatus('Зберігаю...', 'busy');
      send(root.getAttribute('data-api-bulk'), 'POST', {
        role_id: roleId, module: module, mode: bulk.getAttribute('data-bulk')
      }).then(function (data) {
        var granted = data.granted || [];
        root.querySelectorAll('.switch__input[data-role-id="' + roleId + '"][data-module="' + module + '"]')
          .forEach(function (input) {
            input.checked = granted.indexOf(input.getAttribute('data-permission')) !== -1;
          });
        updateCount(data.role_id, data.role_count);
        setStatus('Збережено', 'ok');
      }).catch(function (err) {
        setStatus('Помилка: ' + err.message, 'error');
      }).then(function () {
        buttons.forEach(function (b) { b.disabled = false; });
      });
      return;
    }

    var toggle = e.target.closest('[data-group-toggle]');
    if (toggle) {
      var key = toggle.getAttribute('data-group-toggle');
      var collapsed = toggle.getAttribute('aria-expanded') === 'true';
      setCollapsed(key, collapsed);
      saveCollapsed(key, collapsed);
    }
  });

  function setCollapsed(key, collapsed) {
    var tbody = root.querySelector('.access-group[data-group="' + key + '"]');
    if (!tbody) return;
    var toggle = tbody.querySelector('[data-group-toggle]');
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    tbody.querySelectorAll('.access-module, .access-perm').forEach(function (row) {
      row.hidden = collapsed;
    });
  }

  function loadCollapsed() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
    catch (err) { return []; }
  }

  function saveCollapsed(key, collapsed) {
    var list = loadCollapsed().filter(function (k) { return k !== key; });
    if (collapsed) list.push(key);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(list)); } catch (err) { /* приватний режим */ }
  }

  loadCollapsed().forEach(function (key) { setCollapsed(key, true); });

  /* ---- пошук ---- */
  if (search) {
    search.addEventListener('input', function () {
      var q = search.value.trim().toLowerCase();
      root.querySelectorAll('.access-group').forEach(function (tbody) {
        var anyVisible = false;
        tbody.querySelectorAll('.access-module').forEach(function (moduleRow) {
          var module = moduleRow.getAttribute('data-module');
          var visible = 0;
          tbody.querySelectorAll('.access-perm .switch__input[data-module="' + module + '"]').forEach(function (input) {
            var row = input.closest('.access-perm');
            var match = !q || row.getAttribute('data-search').indexOf(q) !== -1;
            row.hidden = !match;
            if (match) visible += 1;
          });
          moduleRow.hidden = visible === 0;
          if (visible) anyVisible = true;
        });
        if (q) tbody.querySelector('[data-group-toggle]').setAttribute('aria-expanded', 'true');
        tbody.hidden = q ? !anyVisible : false;
      });
      if (!q) loadCollapsed().forEach(function (key) { setCollapsed(key, true); });
    });
  }
})();
```

- [ ] **Step 6: CSS розкладки `page-admin-access.css`**

```css
/* page-admin-access.css -- розкладка сторінки /admin/access. Лише сітка,
   ширини й прилипання; декор беруть компоненти admin.css / common.css. */

.access-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 24px;
  align-items: start;
}

.access-matrix {
  min-width: 0;
}

.access-group__head th {
  text-align: left;
  background: var(--iprm-surface-inset);
}

.access-module th,
.access-module td {
  background: var(--iprm-surface-inset);
}

.access-perm:hover td {
  background: var(--iprm-accent-light);
}

.access-group[hidden] {
  display: none;
}

@media (max-width: 1100px) {
  .access-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}

.access-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}

.access-toolbar__search {
  max-width: 320px;
}

.access-status {
  font-size: 0.8125rem;
  color: var(--iprm-text-light);
}

.access-status[data-state='ok'] {
  color: var(--iprm-success);
}

.access-status[data-state='error'] {
  color: var(--iprm-error);
}

.access-matrix__scroll {
  max-height: calc(100vh - 220px);
  overflow: auto;
}

.access-matrix__table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
}

.access-matrix__label {
  min-width: 260px;
}

.access-matrix__role {
  min-width: 120px;
  text-align: center;
  vertical-align: bottom;
}

.access-matrix__role-name {
  display: block;
}

.access-matrix__count {
  display: block;
  font-size: 0.75rem;
  font-weight: 400;
  color: var(--iprm-text-light);
}

.access-group__toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  color: inherit;
}

.access-group__toggle[aria-expanded='false'] .access-group__chevron {
  transform: rotate(-90deg);
}

.access-module__title {
  text-align: left;
  font-weight: 600;
}

.access-module__bulk {
  text-align: center;
  white-space: nowrap;
}

.access-perm__label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.access-perm__code {
  font-family: var(--iprm-font-mono);
  font-size: 0.75rem;
  color: var(--iprm-text-light);
}

.access-perm__cell {
  text-align: center;
}

.access-roles {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.access-roles__title {
  margin: 0;
  font-size: 1rem;
}

.access-role {
  padding: 12px 14px;
  border: 1px solid var(--iprm-border);
  border-radius: var(--iprm-radius-md);
  background: var(--iprm-card-bg);
}

.access-role__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.access-role__slug,
.access-role__meta {
  font-size: 0.75rem;
  color: var(--iprm-text-light);
}

.access-role__desc {
  margin: 6px 0 0;
  font-size: 0.8125rem;
}

.access-role__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
```

- [ ] **Step 7: Прогін**

Run: `python -m pytest tests/test_rbac tests/test_design_system -q && python -m pytest -q`
Expected: усі passed

- [ ] **Step 8: Коміт**

```bash
git add app/admin/routes_access.py app/templates/admin/access.html app/static/js/admin-access-matrix.js app/static/css/page-admin-access.css tests/test_rbac/test_access_routes.py
git commit -m "feat(rbac): сторінка матриці прав з автозбереженням і гуртовими діями" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: CRUD ролей (форми) і призначення ролей у картці користувача

**Files:**
- Modify: `app/admin/routes_access.py`, `app/admin/forms.py`, `app/admin/routes_users.py`, `app/templates/admin/user_detail.html`, `app/templates/admin/users.html`
- Create: `app/templates/admin/access_role_form.html`
- Test: `tests/test_rbac/test_role_routes.py`, `tests/test_rbac/test_user_roles.py`

**Interfaces:**
- Consumes: `service.create_role`, `update_role`, `delete_role`, `reset_role_to_defaults`, `assign_roles`.
- Produces: `RoleForm`; маршрути `access_role_new`, `access_role_edit`, `access_role_delete`, `access_role_reset`, `POST /admin/users/<id>/roles` (`admin.user_roles_update`).

- [ ] **Step 1: Тести**

```python
# tests/test_rbac/test_role_routes.py
from app.models.rbac import Role
from tests.support.rbac import make_super_admin


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_create_role_with_copy(client):
    _login(client, make_super_admin())
    viewer = Role.query.filter_by(name='viewer').one()
    resp = client.post('/admin/access/roles/new', data={
        'name': 't_form_role', 'display_name': 'Форма', 'description': 'опис',
        'color': 'teal', 'sort_order': '70', 'copy_from': str(viewer.id),
    }, follow_redirects=False)
    assert resp.status_code == 302
    role = Role.query.filter_by(name='t_form_role').one()
    assert role.color == 'teal'
    assert {p.name for p in role.permissions} == {p.name for p in viewer.permissions}


def test_create_role_rejects_bad_slug(client):
    _login(client, make_super_admin())
    resp = client.post('/admin/access/roles/new', data={
        'name': 'Bad Slug', 'display_name': 'X', 'color': 'teal', 'sort_order': '70', 'copy_from': '0',
    })
    assert resp.status_code == 200
    assert Role.query.filter_by(name='Bad Slug').first() is None


def test_edit_system_role_changes_label_only(client):
    _login(client, make_super_admin())
    role = Role.query.filter_by(name='content_editor').one()
    resp = client.post(f'/admin/access/roles/{role.id}/edit', data={
        'name': 'hacked', 'display_name': 'Редактор', 'description': '',
        'color': 'blue', 'sort_order': '30', 'copy_from': '0',
    })
    assert resp.status_code == 302
    role = Role.query.filter_by(name='content_editor').one()
    assert role.display_name == 'Редактор'
    role.display_name = 'Редактор контенту'


def test_reset_and_delete(client):
    _login(client, make_super_admin())
    marketer = Role.query.filter_by(name='marketer').one()
    assert client.post(f'/admin/access/roles/{marketer.id}/reset').status_code == 302
    assert client.post(f'/admin/access/roles/{marketer.id}/delete').status_code == 302
    assert Role.query.filter_by(name='marketer').first() is not None  # системна
    client.post('/admin/access/roles/new', data={
        'name': 't_to_delete', 'display_name': 'D', 'color': 'gray', 'sort_order': '90', 'copy_from': '0'})
    role = Role.query.filter_by(name='t_to_delete').one()
    client.post(f'/admin/access/roles/{role.id}/delete')
    assert Role.query.filter_by(name='t_to_delete').first() is None
```

```python
# tests/test_rbac/test_user_roles.py
from app.extensions import db
from app.models.rbac import Role
from tests.support.rbac import make_super_admin, make_user_with_role


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_user_detail_shows_roles_form_and_badges(client):
    boss = make_super_admin()
    target = make_user_with_role('viewer')
    _login(client, boss)
    html = client.get(f'/admin/users/{target.id}').get_data(as_text=True)
    assert 'badge--role' in html
    assert 'Спостерігач' in html
    assert f'/admin/users/{target.id}/roles' in html


def test_assign_roles_via_form(client):
    boss = make_super_admin()
    target = make_user_with_role('viewer')
    manager = Role.query.filter_by(name='manager').one()
    _login(client, boss)
    resp = client.post(f'/admin/users/{target.id}/roles', data={'roles': [str(manager.id)]})
    assert resp.status_code == 302
    db.session.expire(target, ['roles'])
    assert [r.name for r in target.roles] == ['manager']


def test_assign_requires_permission(client):
    actor = make_user_with_role('admin')  # admin не має access.assign
    target = make_user_with_role('viewer')
    _login(client, actor)
    resp = client.post(f'/admin/users/{target.id}/roles', data={'roles': []})
    assert resp.status_code == 403


def test_guard_message_flashes(client):
    boss = make_super_admin()
    _login(client, boss)
    resp = client.post(f'/admin/users/{boss.id}/roles', data={'roles': []}, follow_redirects=True)
    assert 'Не можна зняти super_admin із себе' in resp.get_data(as_text=True)


def test_users_list_filters_by_role(client):
    boss = make_super_admin()
    make_user_with_role('marketer', email='marketer-filter@test.com')
    _login(client, boss)
    html = client.get('/admin/users?role=marketer').get_data(as_text=True)
    assert 'marketer-filter@test.com' in html
    assert boss.email not in html
```

- [ ] **Step 2: Запустити, переконатись, що падає**

Run: `python -m pytest tests/test_rbac/test_role_routes.py tests/test_rbac/test_user_roles.py -q`
Expected: FAIL

- [ ] **Step 3: Форма**

У `app/admin/forms.py` (у кінець) додати:

```python
from wtforms import RadioField  # додати до наявного імпорту з wtforms
from app.rbac import registry as _rbac_registry


class RoleForm(FlaskForm):
    """Роль адмін-панелі. Права ролі правляться в матриці, не тут."""
    name = StringField('Код (латиницею)', validators=[
        DataRequired(), Length(2, 50),
        Regexp(r'^[a-z][a-z0-9_]*$',
               message='Лише малі латинські літери, цифри та підкреслення'),
    ])
    display_name = StringField('Назва', validators=[DataRequired(), Length(1, 100)])
    description = TextAreaField('Опис', validators=[Optional(), Length(max=500)])
    color = RadioField('Колір', choices=[
        (c, _rbac_registry.ROLE_COLOR_LABELS[c]) for c in _rbac_registry.ROLE_COLORS
    ], default='gray')
    sort_order = IntegerField('Порядок у матриці', default=100,
                              validators=[InputRequired(), NumberRange(0, 1000)])
    # 0 = не копіювати. Варіанти виставляє маршрут.
    copy_from = SelectField('Скопіювати права з', coerce=int, default=0,
                            validators=[Optional()])
```

- [ ] **Step 4: Маршрути CRUD (замінити заглушки в `routes_access.py`)**

```python
from app.admin.forms import RoleForm


def _role_form(role=None):
    form = RoleForm(obj=role) if request.method == 'GET' else RoleForm()
    form.copy_from.choices = [(0, 'Не копіювати')] + [
        (r.id, r.display_name) for r in _roles_ordered() if role is None or r.id != role.id
    ]
    return form


@admin_bp.route('/access/roles/new', methods=['GET', 'POST'])
@permission_required('access.manage')
def access_role_new():
    form = _role_form()
    if form.validate_on_submit():
        copy_from = db.session.get(Role, form.copy_from.data) if form.copy_from.data else None
        try:
            service.create_role(form.name.data, form.display_name.data,
                                form.description.data, form.color.data,
                                form.sort_order.data, current_user, copy_from=copy_from)
            db.session.commit()
            flash(f'Роль «{form.display_name.data}» створено', 'success')
            return redirect(url_for('admin.access'))
        except AccessError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
    return render_template('admin/access_role_form.html', form=form, role=None)


@admin_bp.route('/access/roles/<int:role_id>/edit', methods=['GET', 'POST'])
@permission_required('access.manage')
def access_role_edit(role_id):
    role = db.session.get(Role, role_id)
    if role is None:
        abort(404)
    form = _role_form(role)
    if form.validate_on_submit():
        try:
            service.update_role(role, form.display_name.data, form.description.data,
                                form.color.data, form.sort_order.data, current_user,
                                name=form.name.data)
            db.session.commit()
            flash('Роль оновлено', 'success')
            return redirect(url_for('admin.access'))
        except AccessError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
    return render_template('admin/access_role_form.html', form=form, role=role)


def _role_action(role_id, action, success):
    role = db.session.get(Role, role_id)
    if role is None:
        abort(404)
    try:
        action(role, current_user)
        db.session.commit()
        flash(success, 'success')
    except AccessError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('admin.access'))


@admin_bp.route('/access/roles/<int:role_id>/delete', methods=['POST'])
@permission_required('access.manage')
def access_role_delete(role_id):
    return _role_action(role_id, service.delete_role, 'Роль видалено')


@admin_bp.route('/access/roles/<int:role_id>/reset', methods=['POST'])
@permission_required('access.manage')
def access_role_reset(role_id):
    return _role_action(role_id, service.reset_role_to_defaults,
                        'Права ролі повернуто до дефолтів')
```

Для системної ролі поле `name` у формі показується як readonly (сервіс і так ігнорує зміну slug).

- [ ] **Step 5: Шаблон форми `admin/access_role_form.html`**

```jinja
{% extends "admin/base_admin.html" %}

{% block title %}{{ 'Роль: ' ~ role.display_name if role else 'Нова роль' }} | ІПРМ{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}
{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/admin.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="admin-with-sidebar">
  {% include 'admin/partials/_sidebar.html' %}
  <div class="admin-layout">
    <div class="admin-hero">
      <div>
        <div class="admin-breadcrumb">
          <a href="{{ url_for('admin.access') }}" class="admin-breadcrumb__link">Доступ</a>
          <span class="admin-breadcrumb__sep">/</span>
          <span class="admin-breadcrumb__current">{{ role.display_name if role else 'Нова роль' }}</span>
        </div>
        <h1 class="admin-hero__title">{{ 'Редагувати роль' if role else 'Нова роль' }}</h1>
        <p class="admin-hero__subtitle">Права ролі налаштовуються в матриці після збереження.</p>
      </div>
    </div>

    {% include 'partials/flash_messages.html' %}

    <form method="POST" class="admin-form">
      {{ form.hidden_tag() }}
      {% include 'admin/partials/_form_errors.html' %}

      <div class="form-section">
        <div class="admin-form__grid">
          <div class="form-group">
            {{ form.name.label }}
            {{ form.name(class='form-control', readonly=(role.is_system if role else False)) }}
            {% if role and role.is_system %}<p class="form-hint">Код системної ролі не змінюється.</p>{% endif %}
          </div>
          <div class="form-group">
            {{ form.display_name.label }}
            {{ form.display_name(class='form-control') }}
          </div>
          <div class="form-group">
            {{ form.sort_order.label }}
            {{ form.sort_order(class='form-control') }}
          </div>
          {% if not role %}
          <div class="form-group">
            {{ form.copy_from.label }}
            {{ form.copy_from(class='form-control') }}
          </div>
          {% endif %}
        </div>
        <div class="form-group">
          {{ form.description.label }}
          {{ form.description(class='form-control', rows=3) }}
        </div>
        <div class="form-group">
          <label>Колір</label>
          <div class="admin-form__grid">
            {% for value, label in form.color.choices %}
            <label class="role-swatch role-color--{{ value }}">
              <input type="radio" name="{{ form.color.name }}" value="{{ value }}"{% if form.color.data == value %} checked{% endif %}>
              <span class="role-dot"></span> {{ label }}
            </label>
            {% endfor %}
          </div>
        </div>
      </div>

      <div class="admin-form__actions">
        <button type="submit" class="btn-admin btn-admin--primary">Зберегти</button>
        <a href="{{ url_for('admin.access') }}" class="btn-admin btn-admin--secondary">Скасувати</a>
      </div>
    </form>
  </div>
</div>
{% endblock %}
```

(Класи `form-hint`, `form-group`, `admin-form__grid`, `admin-form__actions` уже є в `admin.css`; нових класів у цьому шаблоні не заводити.)

- [ ] **Step 6: Призначення ролей у картці користувача**

`app/admin/routes_users.py`, після `user_detail` додати:

```python
@admin_bp.route('/users/<int:user_id>/roles', methods=['POST'])
@permission_required('access.assign')
def user_roles_update(user_id):
    from app.rbac import service
    from app.rbac.service import AccessError

    user = db.session.get(User, user_id)
    if not user:
        flash('Користувача не знайдено', 'error')
        return redirect(url_for('admin.users'))
    role_ids = {int(v) for v in request.form.getlist('roles') if v.isdigit()}
    try:
        service.assign_roles(user, role_ids, current_user)
        db.session.commit()
        flash('Ролі оновлено', 'success')
    except AccessError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('admin.user_detail', user_id=user.id))
```

(додати `request` до імпорту з `flask`). У `user_detail()` передати в шаблон `all_roles=Role.query.order_by(Role.sort_order, Role.display_name).all()` (імпорт `from app.models.rbac import Role`).

`user_detail.html`: у `admin-hero__subtitle` перед бейджем активності:

```jinja
        {% for role in user.roles %}<span class="badge badge--role role-color--{{ role.color }}"><span class="role-dot"></span> {{ role.display_name }}</span>{% endfor %}
```

Після секції «Картка контакту» додати:

```jinja
    {% if can('access.assign') %}
    <div class="form-section">
      <h3 class="admin-form__section-title">Ролі в адмін-панелі</h3>
      <form method="POST" action="{{ url_for('admin.user_roles_update', user_id=user.id) }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        {% set current_ids = user.roles|map(attribute='id')|list %}
        {% for role in all_roles %}
        <div class="form-group">
          <label for="role-{{ role.id }}">
            <input type="checkbox" id="role-{{ role.id }}" name="roles" value="{{ role.id }}"{% if role.id in current_ids %} checked{% endif %}>
            <span class="role-dot role-color--{{ role.color }}"></span> {{ role.display_name }}{% if role.description %} <span class="admin-text-muted">{{ role.description }}</span>{% endif %}
          </label>
        </div>
        {% endfor %}
        <button type="submit" class="btn-admin btn-admin--primary btn-admin--sm">Зберегти ролі</button>
      </form>
    </div>
    {% endif %}
```

`users.html`: у клітинці імені замість колишнього бейджа `admin`:

```jinja
            {% for role in user.roles %}<span class="badge badge--role badge--sm role-color--{{ role.color }}">{{ role.display_name }}</span>{% endfor %}
```

- [ ] **Step 7: Прогін**

Run: `python -m pytest -q`
Expected: усі passed

- [ ] **Step 8: Коміт**

```bash
git add app/admin/routes_access.py app/admin/forms.py app/admin/routes_users.py app/templates/admin/access_role_form.html app/templates/admin/user_detail.html app/templates/admin/users.html tests/test_rbac/test_role_routes.py tests/test_rbac/test_user_roles.py
git commit -m "feat(rbac): CRUD ролей і призначення ролей у картці користувача" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

# Етап 5. Документація, деплой, перевірка

### Task 13: Документація і крок деплою

**Files:**
- Create: `docs/rbac.md`
- Modify: `README.md`, `docs/models.md`, `docs/routes.md`, `docs/deployment.md`, `.github/workflows/deploy.yml`

- [ ] **Step 1: `docs/rbac.md`**

```markdown
# Ролі та права адмін-панелі (RBAC)

Замінює колишній прапорець `users.is_admin` (прибрано міграцією
`rbac_20260905`). Дизайн: `docs/superpowers/specs/2026-09-05-rbac-access-matrix-design.md`.

## Модель

| Таблиця | Призначення |
|---|---|
| `roles` | роль: `name` (slug), `display_name`, `description`, `color` (ім'я з палітри), `is_system`, `sort_order` |
| `permissions` | право `module.action`; підписи не зберігаються, беруться з реєстру |
| `role_permissions` | розклад роль -> права; правиться ЛИШЕ матрицею `/admin/access` |
| `user_roles` | ролі користувача (`assigned_at`, `assigned_by`) |

`User.roles` (viewonly), `User.is_staff` = має хоч одну роль,
`User.has_permission(name)`.

## Реєстр (`app/rbac/registry.py`)

Модуль = пункт сайдбару, дії `view`/`manage` плюс чутливі (`delete`,
`export`, `import`, `refund`, `settings`, `keys`, `restore`, `receive`,
`assign`). Групи повторюють сайдбар. Дефолти шести системних ролей
застосовуються один раз, при створенні ролі.

## Як додати право до нової в'юхи

1. Дописати дію в `actions` модуля (або новий `Module`) у реєстрі.
2. Поставити `@permission_required('module.action')` на в'юху.
   Форма редагування (GET+POST) отримує `manage`, список -- `view`.
3. Якщо в'юха є в сайдбарі, обгорнути пункт у `{% if can('module.view') %}`.
4. `flask rbac sync` локально; на сервері це робить деплой.
5. Видати право ролям у матриці. Автоматично його має лише `super_admin`.

Сторож `tests/test_rbac/test_guards.py` не пропустить в'юху без декоратора.

## Перевірки

`has_permission(user, name)`: анонім або неактивний -> False; `super_admin`
-> True без читання прав; інакше членство в об'єднанні прав ролей.
Кеш живе в `g`, тобто один запит.

Шаблони: `can('x.view')`, `can_any('a.view', 'b.view')`.

## Запобіжники

* не можна зняти `super_admin` із себе і з останнього носія;
* видати або забрати `super_admin` може лише `super_admin`;
* колонка `super_admin` у матриці заблокована;
* системну роль не видалити й не перейменувати (slug);
* роль із носіями не видаляється.

## Команди

* `flask rbac sync` -- права з реєстру в БД, відсутні системні ролі з
  дефолтами. Наявних ролей не чіпає. Ідемпотентна.
* `flask rbac status` -- ролі, лічильники, розбіжності реєстру й БД.

## Деплой

`flask db upgrade`, потім `flask rbac sync` (крок у
`.github/workflows/deploy.yml`). Dev і prod бази окремі: обом потрібні
обидві команди. Одержувачі службових листів (`notify_admins`) тепер --
носії права `notifications.receive`.
```

- [ ] **Step 2: Решта документів**

`README.md`, таблиця «Документація», після рядка про перенесення реєстрації:

```markdown
| [Ролі та права](docs/rbac.md) | RBAC адмін-панелі: реєстр прав у коді, розклад роль-права в БД, матриця `/admin/access`, запобіжники, `flask rbac sync` |
```

`docs/models.md`: у таблиці `User` прибрати рядок `is_admin`, додати рядок `` `roles` | relationship | Ролі адмінки через `user_roles` (viewonly) ``; після секції User додати:

```markdown
## Role / Permission / UserRole (RBAC)

| Таблиця | Поля |
|---|---|
| `roles` | `id`, `name` (slug, unique), `display_name`, `description`, `color`, `is_system`, `sort_order`, `created_at` |
| `permissions` | `id`, `name` (`module.action`, unique), `module` (index) |
| `role_permissions` | `role_id`, `permission_id` (складений PK, CASCADE) |
| `user_roles` | `user_id`, `role_id` (складений PK), `assigned_at`, `assigned_by` |

Деталі: [docs/rbac.md](rbac.md).
```

`docs/routes.md`, у розділ Admin:

```markdown
| GET | `/admin/access` | Матриця прав і список ролей (`access.view`) |
| PUT | `/admin/access/api/matrix` | Перемкнути право ролі, JSON (`access.manage`) |
| POST | `/admin/access/api/matrix/bulk` | Усі/жодного права модуля для ролі (`access.manage`) |
| GET/POST | `/admin/access/roles/new` | Нова роль (`access.manage`) |
| GET/POST | `/admin/access/roles/<id>/edit` | Редагувати роль (`access.manage`) |
| POST | `/admin/access/roles/<id>/delete` | Видалити несистемну роль без носіїв (`access.manage`) |
| POST | `/admin/access/roles/<id>/reset` | Скинути системну роль до дефолтів (`access.manage`) |
| POST | `/admin/users/<id>/roles` | Призначити ролі користувачу (`access.assign`) |
```

і прибрати рядок про `/admin/users/<id>/toggle-admin`, якщо він там є.

`docs/deployment.md`: у розділ про кроки деплою додати речення: «Після `flask db upgrade` виконується `flask rbac sync`: він додає нові права з коду й створює відсутні системні ролі, не чіпаючи наявних налаштувань матриці.»

`.github/workflows/deploy.yml`: після рядка `            flask db upgrade` додати `            flask rbac sync`.

- [ ] **Step 3: Перевірка**

Run: `python -m pytest -q`
Expected: усі passed

- [ ] **Step 4: Коміт**

```bash
git add docs/rbac.md README.md docs/models.md docs/routes.md docs/deployment.md .github/workflows/deploy.yml
git commit -m "docs(rbac): документація системи ролей, крок flask rbac sync у деплої" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: Візуальна перевірка та застосування міграції на dev

**Files:** без нових файлів.

- [ ] **Step 1: Застосувати міграцію і синк до dev БД**

Run: `flask db upgrade && flask rbac sync && flask rbac status`
Expected: `status` показує 6 ролей, `немає в БД: -`, у `super_admin` стільки носіїв, скільки було `is_admin=True`.

- [ ] **Step 2: Дамп сторінок через тестовий клієнт і headless Chrome**

За процедурою з `docs/`-пам'ятки про візуальну перевірку: зайти super_admin-ом, зберегти HTML `/admin/access`, `/admin/access/roles/new`, `/admin/users/<id>` і зрендерити headless Chrome у світлій і темній темі. Перевірити: sticky-шапка матриці, колонка super_admin заблокована, перемикачі й бейджі ролей однакові на всіх трьох сторінках, у сайдбарі є пункт «Доступ».

- [ ] **Step 3: Ручна перевірка сценаріїв у браузері (dev)**

1. Клік по перемикачу: рядок стану «Зберігаю...» -> «Збережено», лічильник у шапці змінюється, після перезавантаження стан збережено.
2. «нічого» для модуля ролі viewer -> усі перемикачі модуля гаснуть; «усе» -> вмикаються.
3. Створити роль з копіюванням прав; відредагувати колір; видалити.
4. У картці користувача призначити роль; зайти цим користувачем у приватному вікні: сайдбар показує лише дозволене, чужа адреса дає 403.
5. Спроба зняти super_admin із себе -> flash із текстом запобіжника.

- [ ] **Step 4: Повний прогін і фінальна перевірка чистоти**

Run: `python -m pytest -q && python tools/ds/ds_audit.py && grep -rn "is_admin" app/ tests/ --include=*.py --include=*.html`
Expected: тести зелені, аудит без нових дублікатів, grep нічого не знаходить (окрім міграції).

- [ ] **Step 5: Коміт залишків (якщо є) і підсумок**

```bash
git status --short
```

Якщо є правки після візуальної перевірки, закомітити їх як `fix(rbac): правки після візуальної перевірки` з тим самим трейлером. Пуш робить користувач.
