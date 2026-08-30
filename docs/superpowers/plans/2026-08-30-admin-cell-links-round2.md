# План: перелінковка комірок, друга черга

## Контекст

Перша черга (коміт 29dfd72) закрила 22 реєстри. Лишились чотири, у яких
рядок не веде НІКУДИ, і низка точкових значень. Плюс паралельний напрям
щойно додав фільтри, яких раніше бракувало: `post_id` у коментарях блогу
(`app/admin/routes_blog_comments.py:32`) і `verdict` у перф-прогонах
(`app/admin/routes_perf.py:54`).

## Принцип (той самий, що в першій черзі)

1. Сутність веде у свою картку; число -- у перелік, який це число дає;
   технічне значення діагностичного реєстру -- у той самий реєстр,
   звужений за цим значенням.
2. Нуль і прочерк не клікаються.
3. Дві комірки одного рядка не ведуть в одне й те саме місце.
4. Посилання не успадковує поточний зріз сторінки, АЛЕ мусить нейтралізувати
   ненейтральний дефолт цільового реєстру -- інакше клік відкриває сторінку
   без клікнутого рядка. Уже відомі такі дефолти: `error_logs` -- 7 днів,
   `meta_leads` -- без тестових, `registrations_all` -- `scope='upcoming'`
   (`app/admin/routes_registrations.py:476`), `blog_comments` -- статус
   `pending` (`routes_blog_comments.py:41`).

## Global Constraints

- CSS не додавати й не міняти.
- Ніяких inline-стилів, inline-скриптів, емодзі. Коментарі українською, у
  тоні сусіднього коду: ЧОМУ, а не переказ розмітки.
- Задачі 1-2 роутів НЕ чіпають. Роути міняє лише Задача 3, і лише в
  описаному обсязі.
- НЕ комітити.
- Кожне посилання дістає сторож, який перевіряє САМЕ тег навколо значення
  (`re.search(r'<a href="...">\s*<значення>')`). Тест, що пройшов би й на
  неклікабельному тексті, -- дефект. Зразок: `tests/test_routes/test_admin_user_links.py`.
- Тест, що створює користувачів, прибирає їх за собою.
- У дереві паралельно працює інший напрям. Чіпати тільки свої файли.

## Задача 1: чотири реєстри, з яких нікуди не клікнути

Файли: `app/templates/admin/blog_list.html`, `notifications.html`,
`liqpay.html`, `b2b_requests.html`, новий тест
`tests/test_routes/test_admin_deadend_links.py`.

1. `blog_list.html:86` -- «N на модерації» веде в
   `url_for('admin.blog_comments', post_id=post.id, status='pending')`.
   Статус передаємо явно, хоч він і дефолтний: посилання мусить читатись
   без знання дефолтів. Нуль (гілка з прочерком) не клікається.
2. `notifications.html:200` -- адресат -> `notifications_log(q=log.to_email)`;
   `:203` тригер -> `notifications_log(trigger=...)` (поле МОДЕЛІ, не
   `trigger_label`); статус -> `notifications_log(status=...)`. Дзеркалить
   те, що вже зроблено на самій сторінці логу -- звірити з нею розмітку.
3. `liqpay.html:122` -- `REG-<id>` веде в
   `instance_registrations(instance_id=reg.instance_id)`; `:124` -- ПІБ
   платника -> `user_detail(user_id=reg.user.id)`. Якщо в рядку трапляється
   реєстрація без проведення -- гілка лишається текстом.
4. `b2b_requests.html` -- розмір команди -> `b2b_requests_list(team_size=...)`
   (значення поля `team_size`, не `team_size_label`); email заявника ->
   `users(q=req.email)`. FK на користувача в моделі немає
   (`app/models/b2b_request.py`), тож пошук по email -- єдиний точний вхід;
   так і написати в коментарі. ПІБ не лінкувати: вести нікуди.

## Задача 2: точкові значення

Файли: `app/templates/admin/certificates.html`, `course_request_edit.html`,
`material_kit_edit.html`, `materials_picking.html`, `quizzes.html`,
`promo_codes.html`, `perf_runs.html`, новий тест
`tests/test_routes/test_admin_spot_links.py`.

1. `certificates.html:87` -- «Ким видано» -> `user_detail(user_id=cert.issued_by.id)`,
   лише в гілці `{% if cert.issued_by %}`.
2. `course_request_edit.html` -- автор зміни в аудиті
   (`audit.changed_by.email`) -> `user_detail`, лише коли `audit.changed_by`.
3. `material_kit_edit.html` і `materials_picking.html` -- `sku` ->
   `url_for('admin.materials', q=<sku>)` (звірити точну назву ендпоінта
   реєстру матеріалів у `app/admin/routes_materials.py`).
4. `quizzes.html` -- розмір банку і прохідний бал ведуть у редактор тесту
   того ж рядка (`course_quiz_edit` або `instance_quiz_edit` -- узяти той
   самий виклик, що вже стоїть у кнопці цього рядка). Гілка «тесту немає»
   лишається текстом.
5. `promo_codes.html` -- «N з M» використань -> `promo_code_detail`, лише
   коли використань > 0: саме там лежить перелік застосувань.
6. `perf_runs.html` -- вердикт прогону -> `perf_runs(verdict=...)`.
   `pages_warn` / `pages_fail` НЕ чіпати: у `perf_run_detail` немає фільтра
   сторінок за вердиктом, вести нікуди.

## Задача 3: фільтр `user_id` у реєстрі реєстрацій

Файли: `app/admin/routes_registrations.py`,
`app/templates/admin/user_detail.html`, новий тест
`tests/test_routes/test_admin_registrations_user_filter.py`.

1. Додати в `_registration_filters()` фільтр `user_id`
   (`_listing.int_arg('user_id')`) і накласти його в
   `_apply_registration_filters()` як `EventRegistration.user_id == ...`.
   Більше в роутах не міняти нічого: ні дефолтів, ні інших фільтрів.
2. У `user_detail.html`, у заголовку блоку «Реєстрації на заходи», додати
   посилання на `registrations_all(user_id=user.id, scope='all')` --
   «Відкрити в реєстрі». `scope='all'` обов'язковий: дефолт реєстру --
   `upcoming`, і без нього минулі реєстрації людини не видно.
3. У коментарі чесно сказати межу: число в реєстрі користувачів рахує
   реєстрації БЕЗ скасованих (`User.with_registration_count`), а реєстр за
   `user_id` покаже всі, зокрема скасовані -- фільтра «будь-який, крім
   скасованого» в реєстрі не існує. Число в `users.html` лишається
   посиланням на картку і НЕ перенаправляється на реєстр.
