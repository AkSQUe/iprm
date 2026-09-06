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
* роль із носіями не видаляється;
* носій `access.assign` без `super_admin` не може видати собі роль, якої
  не має, ані лишити себе зовсім без ролей.

`access.assign` і `access.manage` за силою дорівнюють супер-адмін-повноваженням:
видавайте їх лише тим, кому довіряєте як адміністратору.

## Команди

* `flask rbac sync` -- права з реєстру в БД, відсутні системні ролі з
  дефолтами. Наявних ролей не чіпає. Ідемпотентна. Право, якого більше
  немає в реєстрі, ВИДАЛЯЄТЬСЯ разом із його видачами ролям (каскад по
  `role_permissions`) -- реєстр головний, а не БД.
* `flask rbac status` -- ролі, лічильники, розбіжності реєстру й БД.

## Деплой

`flask db upgrade`, потім `flask rbac sync` (крок у
`.github/workflows/deploy.yml`). Dev і prod бази окремі: обом потрібні
обидві команди. Одержувачі службових листів (`notify_admins`) тепер --
носії права `notifications.receive`.
