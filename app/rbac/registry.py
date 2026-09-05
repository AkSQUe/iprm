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
