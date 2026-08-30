# План: клік по вмісту комірки відкриває деталі по цьому значенню (адмінка)

## Контекст

У реєстрах адмінки значення в комірках -- мертвий текст, хоч сторінка з
деталями по цьому значенню вже існує. Крайній випадок: картка користувача
`admin.user_detail` досяжна ЛИШЕ зі сторінок Meta Lead, а реєстр
користувачів у неї не веде ніяк. Розбір відповідей `registration_quiz_detail`
досяжний лише з реєстрів реєстрацій, але не зі сторінки результатів
тестування, де він потрібен найбільше.

Зразок, за яким усе рівняється, вже в дереві:
`app/templates/admin/instances.html` (колонка «Реєстрацій») + сторож
`tests/test_routes/test_admin_seats.py::test_registration_count_links_to_registrations`.

## Принцип (єдиний для всіх задач)

1. Клік по СУТНОСТІ (людина, курс, тренер) веде в її картку.
2. Клік по ЧИСЛУ веде в перелік, який це число і дає.
3. Клік по ТЕХНІЧНОМУ ЗНАЧЕННЮ в діагностичному реєстрі (тип помилки,
   адресат листа, кампанія) веде в той самий реєстр, відфільтрований за цим
   значенням, БЕЗ успадкування поточних фільтрів: деталі по значенню -- це
   все по значенню, а не перетин з поточним зрізом.
4. Нуль і прочерк не клікаються.
5. Дві комірки одного рядка не ведуть в одне й те саме місце -- доки для
   другого значення існує точніша ціль. Коли точнішої немає, картка сутності
   перемагає неточний пошук (див. рішення в задачі 1).

## Global Constraints

- CSS не додавати й не міняти. `.admin-table a:not(.btn-admin)`
  (`app/static/css/admin.css:1953`) вже стилізує посилання в реєстрах. Поза
  `.admin-table` -- лише наявні класи.
- Ніяких inline-стилів, inline-скриптів, емодзі. Коментарі -- українською,
  тією ж щільністю й тоном, що в сусідніх рядках шаблону: пояснювати ЧОМУ,
  а не переказувати код.
- Роути, запити, моделі НЕ чіпати. План -- лише шаблони й тести. Якщо для
  лінка бракує фільтра на бекенді, лінк не робиться: це йде у звіт.
- НЕ комітити. Роботу лишати в робочому дереві.
- Кожна задача додає сторож-тест. Тест перевіряє САМЕ тег навколо значення
  (`re.search(r'<a href="...">\s*<значення>', html)`), бо просто наявність
  URL на сторінці проходить і на неклікабельному тексті.
- Тест, що створює користувачів, прибирає їх за собою (див.
  `tests/test_routes/test_admin_seats.py`) -- інакше валиться
  `test_api_v1_clients`.
- Перед звітом запустити `python -m pytest <свій новий тест-файл> -q` і
  вкласти у звіт команду й вивід.
- Файли за межами своєї задачі не чіпати.

## Задача 1: реєстр користувачів (`users.html`)

Файли: `app/templates/admin/users.html`, новий тест
`tests/test_routes/test_admin_user_links.py`.

1. `users.html:74` -- ПІБ у `<strong>` стає посиланням на
   `url_for('admin.user_detail', user_id=user.id)`.
2. `users.html:77` -- `{{ user.registration_count }}`: коли > 0, число стає
   посиланням на `url_for('admin.user_detail', user_id=user.id)`; нуль
   лишається текстом.
   Обґрунтування, яке має бути в коментарі: картка користувача містить
   таблицю його реєстрацій, порахованих тим самим зв'язком, тому це точний
   перелік за цим числом -- на відміну від пошуку по email, який ловить
   чужі адреси-підрядки.
3. Email (`users.html:76`) НЕ чіпати -- він вів би туди ж, куди ПІБ.

Тест: адмін відкриває `/admin/users`, у HTML є `<a href="/admin/users/<id>"`
навколо ПІБ і навколо числа реєстрацій.

## Задача 2: результати тестування (`quiz_results.html`)

Файли: `app/templates/admin/quiz_results.html`, новий тест
`tests/test_routes/test_admin_quiz_result_links.py`.

1. `quiz_results.html:71` -- ПІБ учасника стає посиланням на
   `url_for('admin.user_detail', user_id=row.reg.user.id)`.
2. `quiz_results.html:92-94` -- результат (`row.best`), коли він не `none`,
   стає посиланням на
   `url_for('admin.registration_quiz_detail', reg_id=row.reg.id)`: розбір
   відповідей -- це саме те, звідки взявся бал. Гілка «немає результату»
   лишається текстом.

Тест: сторінка результатів тестування проведення (точний URL узяти з
`app/admin/routes_quizzes.py`, ендпоінт `admin.instance_quiz_results`) для
проведення з однією спробою містить `<a href="/admin/registrations/<reg_id>/quiz"`
навколо балу.

## Задача 3: ПІБ учасника в реєстрах реєстрацій

Файли: `app/templates/admin/registrations.html`,
`app/templates/admin/instance_registrations.html`, новий тест
`tests/test_routes/test_admin_participant_links.py`.

1. `registrations.html:162` і `instance_registrations.html:129` -- ПІБ
   учасника стає посиланням на
   `url_for('admin.participant_edit', reg_id=reg.id)`. Зараз ця дія лежить
   під меню «...» (`partials/_registration_actions.html:16`) -- та сама
   аномалія, яку вже виправили в розкладі.
2. Email під ПІБ стає посиланням на
   `url_for('admin.user_detail', user_id=reg.user.id)`.

Тест: обидві сторінки, обидва посилання.

## Задача 4: число реєстрацій у картці курсу (`course_edit.html`)

Файли: `app/templates/admin/course_edit.html`, новий тест
`tests/test_routes/test_admin_course_edit_links.py`.

`course_edit.html:373` -- `{{ inst.registration_count }}`, коли > 0, стає
посиланням на `url_for('admin.instance_registrations', instance_id=inst.id)`;
нуль лишається текстом. Дзеркалить `instances.html` -- звірити розмітку й тон
коментаря з нею, щоб дві таблиці проведень не розповідали про одне й те саме
різними словами.

## Задача 5: сутність веде у свою картку

Файли: `app/templates/admin/courses.html`, `reviews.html`,
`material_kits.html`, `webhooks.html`, `certificates.html`, новий тест
`tests/test_routes/test_admin_entity_links.py`.

1. `courses.html:109` -- тренер -> `url_for('admin.trainer_edit', trainer_id=course.trainer.id)`.
2. `reviews.html:104` -- курс -> `url_for('admin.course_edit', course_id=r.course.id)`.
3. `material_kits.html:51` -- курс -> `url_for('admin.course_edit', course_id=kit.course.id)`.
4. `webhooks.html:91` -- `d.course_slug` -> `url_for('admin.courses_list', q=d.course_slug)`.
   У доставки немає id курсу, а пошук реєстру курсів шукає по `Course.slug`
   (`app/admin/routes_courses.py:54-56`) -- це єдиний точний вхід.
5. `certificates.html:71-73` -- ПІБ отримувача, і тільки коли є `cert.user`,
   -> `url_for('admin.user_detail', user_id=cert.user.id)`. Назву заходу НЕ
   чіпати: `Certificate.event_title` -- знімок рядком, зв'язку з курсом у
   моделі немає (`app/models/certificate.py:43`).

Тест: по одному посиланню на кожен із п'яти реєстрів (сертифікати -- гілка з
`cert.user`).

## Задача 6: діагностичні реєстри -- значення веде у власний фільтр

Файли: `app/templates/admin/error_logs.html`, `notifications_log.html`,
`meta_leads.html`, новий тест `tests/test_routes/test_admin_diagnostic_links.py`.

1. `error_logs.html:91` -- тип помилки -> `url_for('admin.error_logs', q=log.error_type)`.
   Той самий рядок містить `url_path` -> `url_for('admin.error_logs', q=log.url_path)`
   і код -> `url_for('admin.error_logs', error_code=log.error_code)`.
   Фільтри `q` (шукає по url, error_message, error_type, ip) і `error_code`
   вже є: `app/admin/routes_error_logs.py:44-49`.
2. `notifications_log.html:74` -- адресат -> `url_for('admin.notifications_log', q=log.to_email)`
   (`q` шукає по `EmailLog.to_email`, `app/admin/routes_notifications.py:138`).
   `notifications_log.html:82` -- тригер -> `url_for('admin.notifications_log', trigger=...)`;
   значення взяти з поля моделі, яке приймає фільтр `trigger` у роуті (НЕ з
   `trigger_label`).
3. `meta_leads.html:129` -- кампанія -> `url_for('admin.meta_leads_list', campaign_id=lead.campaign_id)`,
   форма -> `url_for('admin.meta_leads_list', form_id=lead.form_id)`; лише
   коли відповідний id є. Фільтри `campaign_id`/`form_id` вже є.

Жодне з цих посилань не успадковує поточні фільтри сторінки.

## Задача 7: люди в решті реєстрів ведуть у картку користувача

Файли: `app/templates/admin/online_orders.html`, `refund_requests.html`,
`promo_code_detail.html`, `referrals.html`, `referral_detail.html`, новий тест
`tests/test_routes/test_admin_people_links.py`.

1. `online_orders.html:115` -- ПІБ (коли є `order.user`) -> `user_detail`.
2. `refund_requests.html:71` -- ПІБ -> `user_detail`.
3. `promo_code_detail.html:80` -- ПІБ/email -> `user_detail`.
4. `referrals.html` і `referral_detail.html`, таблиці «Нарахування» (цикл по
   `rewards`): ПІБ -> `user_detail(user_id=reg.user.id)`, назва курсу ->
   `instance_registrations(instance_id=reg.instance_id)`. Таблиці `fraud` і
   `top_referrers` уже лінковані -- не чіпати.

## Задача 8: числа й назви ведуть у відфільтрований перелік

Файли: `app/templates/admin/user_detail.html`, `cities.html`,
`course_requests.html`, новий тест
`tests/test_routes/test_admin_filtered_links.py`.

1. `user_detail.html:122` -- `reg.target_title`, і лише коли є
   `reg.instance_id`, -> `instance_registrations`. Онлайн-курси в тій самій
   таблиці instance не мають -- лишаються текстом.
2. `cities.html:130` -- число вживань міста -> `url_for('admin.instances_list', q=row.city.name)`
   (пошук розкладу шукає по `CourseInstance.location`,
   `app/admin/routes_instances.py:86-88`). Прочерк не клікається.
3. `course_requests.html:58` -- число в зведенні по курсах ->
   `url_for('admin.course_requests_list', course_id=course.id)`.
