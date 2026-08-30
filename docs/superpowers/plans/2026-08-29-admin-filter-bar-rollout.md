# Панель фільтрів на решту реєстрів адмінки

## Контекст

Макрос `filter_bar` з `app/templates/admin/partials/_filter_bar.html` разом із
`app/admin/_listing.py` уже обслуговує 25 списків адмінки. Чотири реєстри
лишились поза ним, і два з них через це ТИХО ОБРІЗАЮТЬ вибірку: показують
200 найновіших рядків і жодним чином не повідомляють, що решта є.

Взірець, за яким робиться все нижче: `app/admin/routes_reviews.py:23-53`
(роут) + `app/templates/admin/reviews.html:35` (шаблон).

## Spec

Кожна з чотирьох сторінок після правки мусить:

1. Читати ВСІ свої параметри через `app/admin/_listing.py`
   (`text_arg` / `choice_arg` / `int_arg` / `date_arg` / `per_page_arg`),
   а не через `request.args` напряму.
2. Віддавати в контекст `filters` (повний dict, включно з порожніми
   значеннями) і `filter_args=_listing.filter_args(filters)`.
3. Малювати панель викликом `filter_bar(...)` замість власного пошуку/зрізу.
4. Викликати `empty_state(...)` з `endpoint`, `filter_args` і `base_args`,
   щоб «нічого не знайдено» відрізнялось від «тут порожньо».
5. Не губити зріз: пагінація, чіпси і POST-редіректи ведуть на ті самі
   параметри.

## Global Constraints

- **Жодного нового XLSX-експорту.** `export_endpoint` не передається на
  жодній із чотирьох сторінок. Це рішення користувача, не обговорюється.
- **Жодних фіча-гілок.** Робота і коміти йдуть просто в `main`.
- **Робоча тека не чиста на старті.** Незакомічені
  `app/templates/admin/instances.html`, `tests/test_routes/test_admin_seats.py`,
  а також `scratch_locales.txt`, `scratch_online.txt`,
  `tests/test_seo/test_zz_scratch_dump.py`, `docs/superpowers/**` НЕ належать
  цій роботі. `git add` — лише поіменно по файлах свого завдання, ніколи
  `git add -A` чи `git add .`.
- **Без емодзі в коді.** Без inline-стилів і inline-скриптів.
- **Дизайн-система — джерело істини.** Нових CSS-класів під панель фільтрів
  не заводити: макрос уже приносить свої. Якщо сторінковий CSS
  (`page-admin-*.css`) дублює те, що дає макрос, — прибрати дублікат, а не
  додати ще один.
- **Фільтрувати можна лише в SQL.** Зріз, порахований у Python уже після
  `paginate()`, звузив би тільки поточну сторінку — це та сама пастка, про
  яку попереджає коментар у `routes_quizzes.py:243-246`. Якщо ознака не
  виражається в SQL, фільтра по ній НЕМАЄ.
- **Лічильники — по всьому зрізу, не по сторінці.** Наявні `counts`,
  `passed_count`, `issued_count` рахуються окремими запитами і такими
  лишаються.
- **Тести з користувачами прибирають за собою.** Якщо тест створює `User`
  через `create_with_password` + `commit()`, autouse-фікстура в teardown
  видаляє `User`, `AuthIdentity` і `MedicalProfile` (SQLite без каскадів).
  Взірець: `tests/test_routes/test_admin_online_listings.py`. Інакше падає
  `tests/test_routes/test_api_v1_clients.py::TestParticipants` — і ЛИШЕ в
  повному прогоні.
- **Перевірка — повним прогоном:** `python -m pytest tests/ -q`.
- Мова коментарів і рядків інтерфейсу — українська, як у решті адмінки.

## Task 1: Коментарі блогу — фільтри, пошук і пагінація

**Файли:** `app/admin/routes_blog_comments.py`,
`app/templates/admin/blog_comments.html`.

Зараз `blog_comments()` (рядки 36-46) читає `status` руками і бере
`.limit(200).all()`. Понад 200 коментарів — і найстаріші зникають без сліду.

Зробити:

1. Замінити тіло роута на набір фільтрів через `_listing`:
   - `q` — `_listing.text_arg('q')`, пошук через `_listing.apply_search` по
     `BlogComment.author_name`, `BlogComment.email`, `BlogComment.body`;
   - `post_id` — `_listing.int_arg('post_id')`;
   - `date_from` / `date_to` — `_listing.date_arg`, накладаються через
     `_listing.apply_date_range(query, BlogComment.created_at, ...)`;
   - `per_page` — `_listing.per_page_arg()`.
2. `status` ЛИШАЄТЬСЯ окремим параметром із дефолтом
   `BlogComment.STATUS_PENDING` і далі малюється стрічкою `admin-pills`
   (рядки 33-47 шаблону). У `fields` макроса його НЕ дублювати: два
   керування одним зрізом гірші за одне. Він передається в
   `base_args={'status': status}`, щоб переживати «Застосувати» і «Скинути».
3. Замінити `.limit(200).all()` на
   `query.order_by(desc(BlogComment.created_at)).paginate(page=..., per_page=per_page, error_out=False)`.
   Сторінку брати як `request.args.get('page', 1, type=int)`.
4. Опції фільтра «Допис» — лише дописи, що мають живі коментарі
   (`BlogComment.alive()` join `BlogPost`, distinct,
   `order_by(BlogPost.title)`), інакше селект перетвориться на список усього
   блогу.
5. `_back()` (рядки 23-33) зберігає лише `status`. Розширити: після дії
   повертати на ТОЙ САМИЙ зріз. Значення брати з прихованих полів форми,
   валідуючи їх тим самим способом, що й у роуті (`status` — звірка з
   `STATUSES`; `page` — `type=int`; решта — рядки). Ніяких `request.referrer`:
   причина написана в докстрингу `_back` і лишається в силі.
6. Шаблон: імпортувати `filter_bar` і `pager` додатково до `empty_state`;
   поставити панель під стрічкою пилюль:

       {{ filter_bar(
            endpoint='admin.blog_comments',
            values=filters,
            search={'name': 'q', 'placeholder': 'Пошук за автором, email або текстом'},
            fields=[
              {'name': 'post_id', 'label': 'Допис', 'placeholder': 'Усі дописи', 'options': post_options},
              {'name': 'date_from', 'label': 'Залишені з', 'type': 'date'},
              {'name': 'date_to', 'label': 'Залишені по', 'type': 'date'},
              {'name': 'per_page', 'label': 'Рядків на сторінці', 'placeholder': '50 (типово)', 'options': per_page_options},
            ],
            base_args={'status': status},
          ) }}

   `per_page_options` — це `_listing.PER_PAGE_OPTIONS`, переданий із роута.
7. Після таблиці:
   `{{ pager('admin.blog_comments', pagination, dict(filter_args, status=status)) }}`.
8. `empty_state` викликати як
   `empty_state('admin.blog_comments', filter_args, {'status': status}, icon_name='forum', title='Коментарів немає')`.
   Текст усередині `call` переписати: він більше не має пояснювати зріз —
   це робить сам макрос.
9. Приховані поля `status` у формах дій рядка (`approve`, `spam`, `delete`)
   доповнити рештою параметрів зрізу, щоб `_back()` мав що читати.

**Тести** — новий файл `tests/test_routes/test_admin_more_filters.py`,
секція «Коментарі блогу»:

- пошук по тексту звужує список (знайдений коментар є, чужий — ні);
- фільтр за дописом лишає лише його коментарі;
- при кількості коментарів понад сторінку друга сторінка віддає інші рядки,
  а посилання пагінації несе і `status`, і активний фільтр;
- порожній результат під фільтром друкує «Нічого не знайдено», а не
  «Коментарів немає».

## Task 2: Webhook черга — фільтри, пошук і пагінація

**Файли:** `app/admin/routes_webhooks.py`,
`app/templates/admin/webhooks.html`,
`app/static/css/page-admin-webhooks.css`.

Зараз `webhooks_list()` (рядки 17-43) читає `status` руками і бере
`.limit(200).all()`. Черга росте на кожну зміну курсу й на кожну партнерську
подію, тож обрізання спрацьовує тут швидше за все.

Зробити:

1. Фільтри через `_listing`:
   - `q` — пошук по `WebhookDelivery.event_uuid`, `WebhookDelivery.course_slug`,
     `WebhookDelivery.target_url`, `WebhookDelivery.last_error`;
   - `event_type` — `_listing.choice_arg` по переліку, зібраному з БД
     (`distinct` непорожніх `event_type`, відсортованих). Порожній
     `event_type` означає каталожну подію старого формату, тож у переліку
     має бути окрема опція `catalog` -> «Каталог (курси)», що фільтрує
     `event_type IS NULL OR event_type = ''`;
   - `action` — `_listing.choice_arg('action', {'created': 'Створення', 'updated': 'Оновлення', 'deleted': 'Видалення'})`;
   - `date_from` / `date_to` — по `WebhookDelivery.created_at` через
     `_listing.apply_date_range`;
   - `per_page` — `_listing.per_page_arg()`.
2. `status` ЛИШАЄТЬСЯ окремим параметром: він уже намальований stat-картками
   (рядки 41-56 шаблону), і це добре — картка показує і зріз, і його
   кількість. У `fields` не дублювати; передати
   `base_args={'status': filter_status}`. Значення звірити через
   `_listing.choice_arg('status', WebhookDelivery.STATUS_BADGES)`, щоб
   `?status=<сміття>` не давало порожнього екрана без пояснення.
3. `counts` рахуються по ВСІЙ таблиці і такими лишаються: це кількість у
   черзі, а не в зрізі.
4. Замінити `.limit(200).all()` на `paginate(...)`.
5. Шаблон: імпортувати `filter_bar` і `pager`; панель поставити під
   stat-картками. Блок `wh-results-meta` (рядки 59-68) ПРИБРАТИ повністю:
   «Показано N» і «Скинути фільтр» тепер дає макрос (чіпси плюс «Скинути
   все») і пагінатор (`сторінка / сторінок (усього)`). Разом із розміткою
   прибрати з `page-admin-webhooks.css` правила `.wh-results-meta*`, що
   лишились без споживача.
6. `pager('admin.webhooks_list', pagination, dict(filter_args, status=filter_status))`.
7. `empty_state('admin.webhooks_list', filter_args, {'status': filter_status}, ...)`.
8. `webhook_retry` і `webhook_delete` (рядки 53, 72, 81, 93) редіректять на
   голий `url_for('admin.webhooks_list')` — тобто кожна дія скидає зріз.
   Виправити: повертати на той самий зріз, беручи параметри з прихованих
   полів POST-форми і валідуючи їх тим самим `_listing`-способом, що й у
   роуті списку. Приховані поля додати в обидві форми дій у шаблоні.

**Тести** — секція «Webhook черга» в тому ж файлі:

- пошук по `course_slug` і по `event_uuid` звужує список;
- фільтр `event_type=catalog` віддає рядки з порожнім `event_type`, а не всі
  підряд;
- друга сторінка під фільтром не втрачає ані `status`, ані `q`;
- `webhook_delete` повертає на URL зі збереженим зрізом.

## Task 3: Результати тестування по групі — фільтри і пошук

**Файли:** `app/admin/routes_quizzes.py` (роут `instance_quiz_results`,
рядки 230-303), `app/templates/admin/quiz_results.html`.

Сторінка вже пагінована і вже бере `per_page` через `_listing`, але фільтрів
не має жодного. Перед видачею сертифікатів менеджеру потрібен зріз «хто ще не
склав» — зараз він гортає сторінки очима.

Зробити:

1. Додати фільтри через `_listing`, накладаючи їх на `query` ДО `paginate`:
   - `q` — `_listing.apply_search` по `User.first_name`, `User.last_name`,
     `User.email` (join `User` у запиті вже є);
   - `state` — `_listing.choice_arg` рівно з ТРЬОХ значень, кожне з яких
     виражається в SQL:
     - `passed` -> `EventRegistration.quiz_passed_at.isnot(None)`
     - `not_passed` -> `EventRegistration.quiz_passed_at.is_(None)`
     - `no_certificate` -> `~EventRegistration.certificate.has()`
   - `payment` — `_listing.choice_arg('payment', {'paid': 'Оплачено', 'unpaid': 'Не оплачено'})`
     -> `payment_status == 'paid'` / `payment_status != 'paid'`.
2. Обчислювані стани (`attempts_exhausted`, `in_progress`,
   `profile_incomplete`) фільтрами НЕ стають: вони народжуються в
   `quiz_service.eligibility_map` уже після вибірки сторінки, і фільтр по них
   звузив би лише поточну сторінку. Це прямо заборонено Global Constraints.
   У коді лишити короткий коментар, ЧОМУ перелік `state` саме такий, — інакше
   наступний допише туди `in_progress` і зламає пагінацію мовчки.
3. `total_count`, `passed_count`, `issued_count` рахуються з `base` (уся
   група) і такими лишаються: це показник готовності заходу, а не зрізу.
   Коментар у роуті (рядки 288-291) це вже пояснює — не чіпати.
4. Шаблон: імпортувати `filter_bar` додатково; панель поставити між
   stat-картками і таблицею:

       {{ filter_bar(
            endpoint='admin.instance_quiz_results',
            values=filters,
            search={'name': 'q', 'placeholder': 'Пошук за іменем або email'},
            fields=[
              {'name': 'state', 'label': 'Стан', 'placeholder': 'Будь-який', 'options': state_options},
              {'name': 'payment', 'label': 'Оплата', 'placeholder': 'Будь-яка', 'options': payment_options},
              {'name': 'per_page', 'label': 'Рядків на сторінці', 'placeholder': '50 (типово)', 'options': per_page_options},
            ],
            base_args={'instance_id': instance.id},
          ) }}

   `base_args` тут — параметр ШЛЯХУ, і без нього форма сабмітилась би не на ту
   адресу (див. коментар у макросі про `instance_id`).
5. `pager('admin.instance_quiz_results', pagination, dict(filter_args, instance_id=instance.id))`.
6. `empty_state('admin.instance_quiz_results', filter_args, {'instance_id': instance.id}, icon_name='how_to_reg', title='Реєстрацій немає')`.

**Тести** — секція «Результати тестування»:

- `state=not_passed` не показує того, хто склав, і показує того, хто ні;
- `state=no_certificate` ховає учасника з виданим сертифікатом;
- пошук за прізвищем звужує список;
- лічильники в stat-картках під фільтром НЕ змінюються (вони по всій групі).

## Task 4: Перф-прогони — фільтри за вердиктом, джерелом і датою

**Файли:** `app/admin/routes_perf.py` (роут `perf_runs`, рядки 52-80),
`app/templates/admin/perf_runs.html`.

Сторінка пагінована по 20, фільтрів немає. Прогони з різних джерел (`local`,
`ci`, ім'я машини) непорівнянні між собою — це прямо сказано в коментарі до
колонки `source` в `app/models/perf_run.py:76-78`, — а розділити їх на
сторінці нічим.

Зробити:

1. Фільтри через `_listing`:
   - `verdict` — `_listing.choice_arg` по вердиктах `PerfRun`
     (`VERDICT_OK` / `VERDICT_WARN` / `VERDICT_FAIL`; підписи брати з того ж
     модуля, не вигадувати нових);
   - `source` — `_listing.choice_arg` по переліку `distinct` непорожніх
     `PerfRun.source` з БД;
   - `date_from` / `date_to` — `_listing.apply_date_range` по
     `PerfRun.measured_at`;
   - `q` — пошук по `PerfRun.note` і `PerfRun.base_url`.
2. **Пастка, яку не можна пропустити.** `latest` зараз — це
   `pagination.items[0] if page == 1` (рядок 62), і блок порівняння в шапці
   підписаний як останній прогін. Під фільтром перший рядок сторінки вже НЕ
   останній прогін, і блок почав би брехати. Умову звузити: `latest`
   обчислюється лише коли `page == 1` І жоден фільтр не заданий
   (`not filter_args`). Інакше — `None`, і блок не малюється, як він уже не
   малюється на другій сторінці.
3. `?reveal=1` — окремий параметр, не фільтр: у `filters` він не входить і в
   `filter_args` не потрапляє. Інакше ключ поповз би в чіпси і в посилання
   пагінації, тобто секрет опинився б у кожному URL сторінки.
4. Шаблон: імпортувати `filter_bar`; панель поставити перед таблицею
   (рядок 63). `pager('admin.perf_runs', pagination, filter_args)`.
   `empty_state('admin.perf_runs', filter_args, icon_name='bolt', title='Замірів ще немає')`.

**Тести** — секція «Перф-прогони»:

- `verdict=fail` лишає лише провалені прогони;
- `source=ci` не показує локальних;
- під активним фільтром блок «останній прогін» у шапці не малюється;
- `?reveal=1` не з'являється ні в чіпсах, ні в посиланні пагінації.

## Task 5: Повний прогін і звірка

1. `python -m pytest tests/ -q` — увесь набір, а не лише нові файли. Причина
   саме повного прогону — у Global Constraints.
2. `python tools/ds/ds_audit.py` — переконатись, що прибрані правила
   `page-admin-webhooks.css` не лишили сиріт і що нових дублікатів класів не
   з'явилось.
3. Звірити візуально дампом через тестовий клієнт: чотири сторінки без
   фільтрів і з фільтром — панель згорнута чи розгорнута, чіпси на місці,
   пагінатор несе зріз.
