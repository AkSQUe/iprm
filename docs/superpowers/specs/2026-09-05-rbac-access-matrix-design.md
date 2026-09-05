# RBAC і матриця прав адмін-панелі

Дата: 2026-09-05. Статус: дизайн схвалено, план реалізації далі.

## 1. Навіщо

Сьогодні доступ до адмінки вирішує один прапорець `users.is_admin`.
Усі 261 в'юха блупринта `admin` стоять під `@admin_required`, який перевіряє
лише його. Наслідок: людина або бачить і може все, або не бачить нічого.
Немає способу дати менеджеру реєстрації без налаштувань інтеграцій, а
редактору блог без повернень коштів.

Потрібна система ролей і прав, якою керують із матриці в адмінці, як у
проєкті MM Medic (`d:\site-mm-medic\app\rbac\`), але без успадкованих
там ускладнень.

## 2. Рішення, ухвалені при брейнштормі

| Питання | Рішення |
|---|---|
| Охоплення | Лише адмін-панель. Публічний кабінет, тренери, учасники не зачіпаються. |
| Гранулярність | `view` + `manage` у кожного модуля, окремі права лише для чутливих дій. |
| Джерело правди | Права оголошені в коді й синкаються в БД. Розклад роль -> права живе в БД і правиться лише матрицею. Код сідить дефолти ролі рівно один раз, при її створенні. |
| Персональні права | Немає. Користувач може мати кілька ролей, цього достатньо. |
| Стартові ролі | super_admin, admin, manager, content_editor, marketer, viewer. |
| Захист в'юх | Підхід C: явний декоратор права на кожній в'юсі + зовнішній запобіжник у `before_request` блупринта, що пускає лише носія хоч однієї ролі. |

Свідомо НЕ береться з MM Medic: таблиця оверайдів (непотрібна, бо БД і є
джерелом правди), персональні права, контекстні перевірки, ліниве
підвантаження розділів матриці (у нас близько 90 прав, не 440), окрема
сторінка ролей.

## 3. Модель даних

Файл: `app/models/rbac.py`. Міграція: `rbac_20260905`, `down_revision`
дорівнює поточній голові на момент реалізації (на 2026-09-05 це
`email_trigger_transfer_20260831`; перевірити `flask db heads`).

### 3.1 Таблиці

`roles`

| Колонка | Тип | Примітка |
|---|---|---|
| id | BigInteger PK | |
| name | String(50) unique, not null | slug латиницею: `manager` |
| display_name | String(100) not null | «Менеджер» |
| description | Text | |
| color | String(20) not null, default `gray` | ім'я з палітри, див. 6.4 |
| is_system | Boolean not null, default false | системну не можна видалити й перейменувати slug |
| sort_order | Integer not null, default 100 | порядок колонок у матриці |
| created_at | DateTime(tz) | |

`permissions`

| Колонка | Тип | Примітка |
|---|---|---|
| id | BigInteger PK | |
| name | String(100) unique, not null | `courses.manage` |
| module | String(50) not null, index | `courses` |

Підписи прав у БД НЕ зберігаються: вони беруться з реєстру в коді при
рендері. Право, якого немає в реєстрі, при синку видаляється.

`role_permissions`: `role_id` FK roles CASCADE, `permission_id` FK
permissions CASCADE, складений PK.

`user_roles`: `user_id` FK users CASCADE, `role_id` FK roles CASCADE,
складений PK, `assigned_at` DateTime(tz), `assigned_by` FK users SET NULL.

### 3.2 Зміни в `User`

* Колонка `is_admin` ВИДАЛЯЄТЬСЯ.
* `User.roles`: relationship до `Role` через `user_roles`, `lazy='select'`;
  списки завантажують через `selectinload(User.roles)`.
* `User.is_staff`: property, `bool(self.roles)`. Замінює `is_admin` там,
  де питання було «чи це співробітник».
* `User.has_permission(name)`: делегує в `app.rbac.service`.

### 3.3 Міграція `rbac_20260905`

upgrade, в одній транзакції:

1. створити 4 таблиці;
2. `INSERT INTO roles` рядок `super_admin` (display_name «Супер-адміністратор»,
   color `red`, is_system true, sort_order 0);
3. `INSERT INTO user_roles (user_id, role_id) SELECT id, <super_admin.id>
   FROM users WHERE is_admin IS TRUE`;
4. `DROP COLUMN users.is_admin`.

downgrade: додати `is_admin` (default false), виставити true носіям
`super_admin`, видалити 4 таблиці.

Решту ролей і всі права створює `flask rbac sync` (розділ 8), а не
міграція: міграції не імпортують реєстр застосунку. Між `upgrade` і
`sync` адмінка працює для super_admin, бо він проходить перевірки без
читання прав.

## 4. Реєстр прав у коді

Файл: `app/rbac/registry.py`. Пакет `app/rbac/` складається з
`__init__.py` (публічний API), `registry.py`, `service.py`,
`decorators.py`, `cli.py`.

### 4.1 Формат

```python
Module(name='courses', label='Курси', group='content',
       actions=('view', 'manage', 'delete', 'export', 'import'))
```

Групи фіксовані й повторюють групи сайдбару плюс дві службові:
`dashboard` «Панель», `content` «Контент», `sales` «Продажі»,
`audience` «Аудиторія», `tools` «Інструменти», `system` «Система»,
`access` «Доступ».

Підписи дій єдині для всієї матриці:

| Дія | Підпис | Сенс |
|---|---|---|
| view | Перегляд | усі GET-сторінки списків і карток, JSON для списків |
| manage | Керування | створення, редагування, зміна статусів, службові POST-дії |
| delete | Видалення | явні маршрути видалення й масового видалення |
| export | Експорт | xlsx-звіти, завантаження файлів |
| import | Імпорт | завантаження xlsx із застосуванням |
| refund | Повернення коштів | лише `registrations` |
| settings | Налаштування інтеграції | лише `meta_leads` (токен, підписка, тест-режим) |
| keys | Ключі й секрети | лише `integrations` |
| restore | Відновлення з копії | лише `backup` |
| receive | Службові листи | лише `notifications` |
| assign | Призначення ролей | лише `access` |

Правило для маршруту з GET і POST на одній адресі (форма редагування):
потрібне право `manage`. `view` дають лише маршрутам, які нічого не
змінюють.

### 4.2 Таблиця модулів

Ім'я модуля збігається з пунктом сайдбару. Сторінки без свого пункту
приклеєні до батька (колонка «Охоплює»).

| Модуль | Підпис | Група | Дії | Охоплює (файли маршрутів) |
|---|---|---|---|---|
| dashboard | Панель | dashboard | view | `routes_stubs.dashboard` |
| courses | Курси | content | view manage delete export import | routes_courses, routes_course_tariffs, courses_* у routes_xlsx |
| instances | Розклад | content | view manage delete export import | routes_instances, routes_instance_tariffs, instances_* у routes_xlsx |
| online_courses | Онлайн-курси | content | view manage | routes_online_courses |
| cities | Довідник локацій | content | view manage delete | routes_cities |
| quizzes | Тестування | content | view manage delete | routes_quizzes |
| course_requests | Запити на курси | content | view manage delete export | routes_course_requests |
| b2b_requests | B2B-заявки | content | view manage export | routes_b2b_requests |
| meta_leads | Ліди Meta | content | view manage delete export settings | routes_meta_leads (форми, події, налаштування) |
| refund_requests | Заявки на повернення | content | view manage export | routes_refund_requests |
| trainers | Тренери | content | view manage delete | routes_trainers |
| blog | Блог | content | view manage delete | routes_blog, routes_blog_comments |
| media | Медіа | content | view manage delete | routes_media, routes_uploads |
| translations | Переклади | content | manage export import | routes_translations, translations_* у routes_xlsx |
| registrations | Реєстрації | sales | view manage export import refund | routes_registrations, routes_participants, routes_payments (`/payments`), routes_refunds |
| online_orders | Онлайн-курси: замовлення | sales | view manage export | routes_online_orders |
| certificates | Сертифікати | sales | view manage export | routes_certificates, `certificate_revoke` |
| referrals | Реферали | sales | view manage export | routes_referrals |
| promo_codes | Промокоди | sales | view manage delete export | routes_promo_codes |
| users | Користувачі | audience | view export | routes_users (крім призначення ролей) |
| reviews | Відгуки | audience | view manage delete | routes_reviews |
| cert_generator | Генератор сертифікатів | tools | view manage | routes_tools |
| marketing | Маркетинг | system | view manage | `routes_stubs.marketing`, routes_analytics |
| notifications | Сповіщення | system | view manage export receive | routes_notifications, routes_notifications_recipients |
| integrations | Інтеграції | system | view manage keys | routes_stubs (hub, health, io), routes_payments (liqpay), routes_recaptcha, routes_google_oauth, routes_apple_signin, routes_meta_pixel, routes_posthog, routes_sintegrum |
| webhooks | Webhook черга | system | view manage delete | routes_webhooks |
| materials | Резервування матеріалів | system | view manage delete export import | routes_materials, routes_material_kits |
| error_logs | Журнал помилок | system | view manage delete export | routes_error_logs |
| perf | Швидкість сторінок | system | view manage | routes_perf |
| design_system | Дизайн-система | system | view | routes_design_system |
| settings | Налаштування | system | manage | routes_settings |
| backup | Резервні копії | system | view manage delete export restore | routes_backup |
| access | Доступ | access | view manage assign | routes_access (нова), `users/<id>/roles` |

Уточнення прив'язки чутливих дій:

* `integrations.keys`: `liqpay_save_keys`, `recaptcha_save_keys`,
  `google_oauth_save`, `apple_signin_save`, `meta_pixel_save`,
  `posthog_save`, `sintegrum_save`, `integrations_export`,
  `integrations_import_preview`, `integrations_import_apply`.
  Тести підключень і синк Sintegrum: `integrations.manage`.
* `meta_leads.settings`: усе під `/meta-leads/settings/*`.
* `registrations.refund`: маршрут у routes_refunds.
* `backup.export`: `backup_download`; `backup.restore`: `backup_restore`.
* `notifications.receive` не захищає жодного маршруту: це ознака «кому
  слати службові листи» (розділ 7).

Загалом близько 90 прав. Точна кількість не фіксується: реєстр і є
переліком.

### 4.3 Дефолти ролей

Задаються в реєстрі як списки з підстановкою `module.*`. Застосовуються
рівно один раз, коли `flask rbac sync` створює роль, якої ще немає в БД.
Далі БД головна.

| Роль | display_name | Колір | Дефолт |
|---|---|---|---|
| super_admin | Супер-адміністратор | red | обхід перевірок, у матриці колонка заблокована й повністю увімкнена |
| admin | Адміністратор | orange | усе, крім `access.*`, `settings.*`, `integrations.keys`, `backup.restore`, `backup.delete` |
| manager | Менеджер | green | `registrations.*`, `online_orders.*`, `certificates.*`, `refund_requests.*`, `course_requests.*`, `b2b_requests.*`, `promo_codes.view/manage/export`, `referrals.view/export`, `meta_leads.view/manage/export`, `cert_generator.*`, `users.view`, `courses.view`, `instances.view`, `quizzes.view`, `materials.view`, `dashboard.view` |
| content_editor | Редактор контенту | blue | `courses.*`, `instances.*`, `online_courses.*`, `cities.*`, `quizzes.*`, `trainers.*`, `blog.*`, `media.*`, `reviews.*`, `translations.*`, `registrations.view`, `dashboard.view` |
| marketer | Маркетолог | violet | `meta_leads.*`, `marketing.*`, `promo_codes.*`, `referrals.*`, `reviews.view/manage`, `users.view`, `courses.view`, `instances.view`, `b2b_requests.view`, `course_requests.view`, `dashboard.view` |
| viewer | Спостерігач | gray | усі `*.view` у групах dashboard, content, sales, audience, tools |

Усі шість ролей `is_system=True`. Нове право, додане в реєстр пізніше, не
отримує жодна роль, крім super_admin через обхід. Хочеш видати, іди в
матрицю. Це fail-closed за задумом.

## 5. Перевірка доступу

### 5.1 Сервіс (`app/rbac/service.py`)

* `effective_permissions(user) -> frozenset[str]`: об'єднання прав усіх
  ролей користувача. Рахується один раз на запит і кешується в `g` за
  `user.id`. Один SQL-запит: `permissions JOIN role_permissions JOIN
  user_roles WHERE user_id = ?`.
* `has_permission(user, name)`: `False` для анонімного або неактивного;
  `True` без читання прав, якщо серед ролей є `super_admin`; інакше
  членство в `effective_permissions`.
* `is_super_admin(user)`.
* `sync()`: розділ 8.
* `assign_roles(user, role_ids, actor)`: заміна набору ролей із
  запобіжниками (розділ 6.5), пише в `audit`.

Кеш живе лише в межах запиту, тож правка матриці впливає на інших
користувачів з їхнього наступного запиту. Міжзапитного кешу немає
навмисно.

### 5.2 Декоратори (`app/rbac/decorators.py`)

* `permission_required(*names)`: пропускає, якщо є ХОЧ ОДНЕ з названих
  прав. Анонімного веде на логін із flash (як зараз `admin_required`);
  автентифікованого без права: `abort(403)`; для запитів із
  `Accept: application/json` або шляхів `/api/`: JSON `{"error":
  "forbidden"}` з 403.
* Декоратор ставить на в'юху атрибут `_rbac_permissions = names`. За ним
  працює тест-сторож (розділ 9).
* `admin_required` видаляється. Жодної в'юхи без явного права.

### 5.3 Зовнішній запобіжник

`admin_bp.before_request`: якщо `current_user` не автентифікований, той
самий редирект на логін; якщо автентифікований, але `not is_staff`,
`abort(403)`. Це другий шар: в'юха без декоратора (якби тест-сторож
вимкнули) все одно закрита для не-співробітників.

### 5.4 Шаблони

Глобальні функції Jinja, зареєстровані у `create_app`:
`can(name)`, `can_any(*names)`. Обидві працюють через
`effective_permissions` поточного користувача, тож десяток викликів у
сайдбарі коштує один запит.

Сайдбар `admin/partials/_sidebar.html`: кожен пункт обгорнутий у
`{% if can('<module>.view') %}` (для `translations` і `settings`,
де немає `view`, у `can('<module>.manage')`). Група обгорнута в
`can_any(...)` з правами своїх пунктів і не рендериться порожньою.
Посилання «Доступ» додається в групу Система під `access.view`.

Шапка публічного сайту (`partials/header.html`): `current_user.is_admin`
замінюється на `current_user.is_staff` в обох місцях.

### 5.5 Дашборд

`dashboard.view` мають усі шість ролей за дефолтом. Віджети дашборду не
фільтруються за правами в цій ітерації.

## 6. Сторінка «Доступ»: матриця і ролі

Маршрути в новому `app/admin/routes_access.py`, форми в
`app/admin/forms.py`, шаблони `admin/access.html`,
`admin/access_role_form.html`, JS `static/js/admin-access-matrix.js`,
CSS `static/css/page-admin-access.css` (лише сітка й ширини).

### 6.1 Маршрути

| Метод і шлях | Право | Що робить |
|---|---|---|
| GET `/admin/access` | access.view | сторінка матриці зі списком ролей |
| PUT `/admin/access/api/matrix` | access.manage | JSON `{role_id, permission, granted}`; відповідь `{ok, role_count}` |
| POST `/admin/access/api/matrix/bulk` | access.manage | JSON `{role_id, module, mode: "all" або "none"}`; відповідь з новим набором прав модуля для ролі й лічильником |
| GET, POST `/admin/access/roles/new` | access.manage | форма нової ролі; поле «Скопіювати права з» (select ролей) замінює окремий клон |
| GET, POST `/admin/access/roles/<id>/edit` | access.manage | підпис, опис, колір, порядок; slug лише для несистемної |
| POST `/admin/access/roles/<id>/delete` | access.manage | лише несистемна і лише без носіїв; інакше flash з кількістю носіїв |
| POST `/admin/access/roles/<id>/reset` | access.manage | системну роль повертає до дефолтів реєстру |
| POST `/admin/users/<id>/roles` | access.assign | замінює набір ролей користувача |

Усі POST-форми через Flask-WTF з CSRF. PUT і POST JSON несуть заголовок
`X-CSRFToken` з meta-тега, як у наявних admin-скриптах.

### 6.2 Матриця

* Колонки: ролі за `sort_order`, у шапці крапка кольору, підпис і
  лічильник «n з N». Шапка sticky.
* Рядки: групи в порядку реєстру, всередині модулі, всередині права.
  Групи згортаються, стан згортання пам'ятається в `localStorage`.
  Пошук фільтрує рядки за підписом і кодом права.
* Клітинка: перемикач. Колонка `super_admin` увімкнена й заблокована.
  Для користувача з `access.view` без `access.manage` усі перемикачі
  заблоковані, а рядок стану каже «лише перегляд».
* Збереження: одразу після кліку, PUT на кожну зміну. Оптимістичне
  оновлення з відкатом при помилці й повідомленням у рядку стану
  («Збережено», «Зберігаю...», «Помилка, зміну скасовано»).
* Гуртові дії в заголовку модуля для кожної ролі: «усе», «нічого».
  Гуртових дій на всю роль немає навмисно, як і в MM Medic: 90 прав
  одним кліком не переглянеш.
* Рендер повний, без лінивого підвантаження: ~90 рядків на 6 колонок.

### 6.3 Список ролей

Праворуч від матриці (на вузьких екранах під нею): картки ролей із
крапкою кольору, підписом, кількістю прав і носіїв, кнопками
«Редагувати», «Скинути до дефолтів» (лише системна), «Видалити» (лише
несистемна без носіїв). Кнопка «Нова роль» веде на форму.

### 6.4 Палітра кольорів

Роль зберігає ІМ'Я кольору, не hex: `red`, `orange`, `amber`, `green`,
`teal`, `blue`, `violet`, `gray`. Кожному відповідає клас
`.role-color--<name>`, що виставляє `--role-color` із токенів
дизайн-системи. Це прибирає inline-стилі й тримає бейджі однаковими на
всіх сторінках. Форма ролі показує палітру як радіокнопки з кружками.

### 6.5 Запобіжники

* Не можна зняти `super_admin` із себе.
* Не можна забрати роль `super_admin` в останнього її носія.
* Видати або забрати `super_admin` може лише super_admin.
* Права колонки `super_admin` у матриці не редагуються (API повертає 400).
* Системну роль не можна видалити або змінити їй slug.
* Видалення несистемної ролі з носіями відхиляється; спочатку зняти.
* Кожна зміна ролей, прав і призначень пише рядок в `audit`-логер:
  хто, кому або якій ролі, що саме.

### 6.6 Компоненти дизайн-системи

Нові або змінені компоненти живуть у компонентному CSS і показуються в
каталозі `/admin/design-system`:

* перемикач `.switch` (у системі його ще немає);
* бейдж ролі: наявний `.badge` плюс модифікатор кольору через
  `.role-color--*`;
* крапка кольору `.role-dot`.

У `page-admin-access.css` лишається лише розкладка: сітка матриці,
sticky-шапка, ширини колонок, прилипання рядка стану.

## 7. Що стається з 25 місцями, які читали `is_admin`

| Місце | Зміна |
|---|---|
| `app/admin/decorators.py` | файл видаляється; замість нього `app/rbac/decorators.py` |
| `partials/header.html` (2) | `current_user.is_staff` |
| `partials/_posthog.html` | `data-ph-role` = `staff` або `user` за `is_staff` |
| `routes_users.py` фільтр «Роль» | select реальних ролей; фільтр `User.roles.any(Role.id == ?)`; окреме значення «без ролей» |
| `routes_users.py::toggle_admin` | видаляється; на його місці `POST /users/<id>/roles` |
| `templates/admin/users.html` | замість кнопки «Надати адміна» бейджі ролей; форма призначення в картці |
| `templates/admin/user_detail.html` | бейджі ролей у підзаголовку; секція «Ролі» з чекбоксами під `can('access.assign')` |
| `services/notification_recipients.py` `notify_admins` | одержувачі = активні користувачі з ефективним правом `notifications.receive`; докстрінг і підпис у `notifications_recipients.html` оновити |
| `services/xlsx_reports.py` користувачі | колонка «Адмін» стає «Ролі» (підписи через кому) |
| `routes_meta_leads.py:716` | `user.is_staff` |
| `routes_meta_leads.py:773` | `~User.roles.any()` замість `User.is_admin.is_(False)` |
| `models/material_reservation.py` коментар | оновити текст «IPRM has no role system» |

Публічні маршрути, що використовували `admin_required`, отримують
конкретне право за таблицею 4.2. `main.design_system` лише редиректить і
права не потребує.

## 8. Синк, CLI, деплой

`flask rbac sync` (`app/rbac/cli.py`, реєструється в `create_app` поруч
із іншими командами):

1. для кожного права з реєстру `INSERT ... ON CONFLICT DO NOTHING`;
2. права, яких у реєстрі немає, видалити (каскадом підуть
   `role_permissions`);
3. для кожної системної ролі з реєстру, якої немає в БД: створити й
   видати дефолти з 4.3;
4. наявних ролей і їхніх прав НЕ торкатись;
5. вивести підсумок: додано, видалено, створено ролей.

Команда ідемпотентна. Застосунок при старті синк НЕ запускає.

`flask rbac status`: список ролей з кількістю прав і носіїв, права з
реєстру, яких немає в БД, і навпаки.

Деплой (`.github/workflows/deploy.yml`, крок із `flask db upgrade`):
одразу після нього `flask rbac sync`. Порядок обов'язковий: міграція дає
таблиці й переносить адмінів, синк заповнює права й решту ролей. Dev і
prod бази роздільні, обидві потребують і міграції, і синку.

Локально після `git pull`: `flask db upgrade && flask rbac sync`.

## 9. Тести

Каталог `tests/test_rbac/` плюс правки наявних.

Сторожі:

* `test_every_admin_endpoint_declares_permission`: обходить
  `app.view_functions` з префіксом `admin.` і вимагає атрибут
  `_rbac_permissions` у кожної; кожне назване право є в реєстрі.
* `test_registry_is_consistent`: імена унікальні, кожна дія з дозволеного
  списку, кожна група відома, кожен модуль має `view` або `manage`.
* `test_sidebar_links_are_gated`: парсить `_sidebar.html`, кожен
  `url_for('admin.X')` стоїть усередині `can(...)` з правом існуючого
  модуля.
* `test_role_defaults_reference_existing_permissions`.

Сервіс: обхід super_admin; ефективні права об'єднуються з кількох ролей;
кеш у `g` дає один запит на кілька перевірок; неактивний користувач без
прав; запобіжники 6.5 кожен окремо.

Маршрути: користувач із `viewer` отримує 200 на списку й 403 на
редагуванні; анонім редиректиться; JSON-запит без права дає 403 JSON;
PUT матриці змінює право і лічильник; PUT на super_admin дає 400; bulk
all/none; CRUD ролі з копіюванням прав; видалення ролі з носіями
відхиляється; призначення ролей із запобіжниками; сайдбар не показує
пункти без права.

Синк: додає нові, видаляє зайві, не чіпає наявні зв'язки, створює
відсутню системну роль з дефолтами.

Наявні тести: 68 файлів створюють користувача через
`User.create_with_password(..., is_admin=True)`. Для них у
`tests/support/rbac.py` з'являється `make_super_admin(**kwargs)`, що
створює користувача й видає роль, і `grant_role(user, name)`. Заміна
робиться одним проходом по файлах, без сумісного шима в продакшн-коді.
Фікстура `app` у `conftest.py` після `create_all` викликає
`rbac.service.sync()`, щоб ролі й права існували в кожному тесті.
Тести, що створюють користувачів, прибирають їх у teardown (вимога з
пам'ятки про ліміт користувачів у `test_api_v1_clients`).

Візуальна перевірка матриці: дамп сторінки через тестовий клієнт і
headless Chrome, за процедурою з пам'ятки про візуальну перевірку.

## 10. Документація

* Новий `docs/rbac.md`: модель, реєстр, як додати право до нової в'юхи,
  як додати роль, як працює синк, запобіжники, деплой.
* README: рядок у таблиці «Документація».
* `docs/models.md`: чотири таблиці; `docs/routes.md`: нові маршрути;
  `docs/deployment.md`: крок `flask rbac sync`.
* Каталог дизайн-системи: перемикач, бейдж ролі, крапка.

## 11. Поза обсягом

Робиться окремою ітерацією, якщо знадобиться:

* персональні права поверх ролей (окрема таблиця `user_permissions`);
* scope-фільтри даних (тренер бачить лише свої заходи);
* права на публічну частину сайту;
* фільтрація віджетів дашборду за правами;
* міжзапитний кеш прав.

## 12. Порядок реалізації (для плану)

1. Пакет `app/rbac/` і моделі, міграція, `flask rbac sync`, тести
   сервісу й синку.
2. Декоратор і запобіжник блупринта; заміна `admin_required` у 50 файлах
   за таблицею 4.2; тест-сторож ендпоінтів; хелпери тестів і заміна в
   68 файлах; зелений прогін.
3. Сайдбар, шапка, `can`/`can_any`, решта 25 місць із розділу 7.
4. Сторінка «Доступ»: матриця, API, ролі, компоненти дизайн-системи,
   каталог.
5. Призначення ролей у картці користувача, фільтр за роллю, бейджі.
6. Документація, деплой-крок, візуальна перевірка.
