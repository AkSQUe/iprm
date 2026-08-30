# Пагінація чотирьох вхідних реєстрів адмінки

## Контекст

Попередній прохід (`2026-08-29-admin-filter-bar-rollout.md`) прибрав тихе
обрізання на 200 рядках із коментарів блогу й черги вебхуків. Обхід решти
адмінки після нього показав інший, м'якший дефект того ж роду на чотирьох
сторінках: фільтри в них є, а пагінації немає — роут тягне ВСЮ таблицю
`.all()` на кожен рендер.

| Сторінка | Роут | Запит |
|---|---|---|
| B2B-заявки | `app/admin/routes_b2b_requests.py:48` | `_b2b_query(filters).all()` |
| Заявки на курси | `app/admin/routes_course_requests.py:52` | `_course_requests_query(filters).all()` |
| Заявки на повернення | `app/admin/routes_refund_requests.py:72` | `_query(filters).all()` |
| Відгуки | `app/admin/routes_reviews.py:43` | `query.order_by(...).all()` |

Усі чотири ростуть від вхідного потоку і не мають стелі. Це НЕ той самий
дефект, що `.limit(200)`: рядки не ховаються, сторінка просто важчає, доки не
впреться в 60-секундний зріз nginx.

Механіка вже стоїть і перевірена на користувачах, сертифікатах і реєстрі
реєстрацій: `_listing.per_page_arg()` + `paginate` + `pager` + поле «Рядків на
сторінці». Взірець: `app/admin/routes_users.py:35` і `:98-104` плюс
`app/templates/admin/users.html`.

## Spec

Кожна з чотирьох сторінок після правки мусить:

1. Пагінувати список у роуті СТОРІНКИ через
   `query.paginate(page=..., per_page=..., error_out=False)`.
2. Читати `per_page` двома окремими викликами, за наявною конвенцією:
   `_listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES)` — рядок у
   `filters` (для чіпса і селекта), `_listing.per_page_arg()` — int у
   `paginate`.
3. Показувати поле «Рядків на сторінці» в `fields` макроса `filter_bar` з
   `_listing.PER_PAGE_OPTIONS` і плейсхолдером `'50 (типово)'`.
4. Малювати `pager(<endpoint>, pagination, filter_args)` під таблицею.
5. Лишити ЕКСПОРТ по всьому зрізу, а не по сторінці.
6. Лишити лічильники по всьому набору, а не по сторінці.

## Global Constraints

- **Експорт не чіпати. Взагалі.** У кожній із чотирьох пар роутів список і
  експорт ділять один хелпер запиту (`_b2b_query`, `_course_requests_query`,
  `_query`). Пагінація ставиться ТІЛЬКИ в роут сторінки. Якщо хтось «зведе»
  спільний хелпер до пагінованого, xlsx мовчки стане однією сторінкою даних —
  а по файлу заявок на повернення звіряють ГРОШІ. Стеля `MAX_EXPORT_ROWS` в
  `_listing` уже є і лишається єдиним обмежувачем експорту.
- **Лічильники — окремими запитами, як зараз.** `new_count`
  (`routes_b2b_requests.py:55`, `routes_refund_requests.py:78`) і
  `counts_by_course` (`routes_course_requests.py:54-64`) рахуються власними
  запитами незалежно від списку. Не перенаправляти їх на `pagination.items`.
- **Порядок сортування зберегти побайтово.** Він у цих реєстрів змістовний:
  - заявки на повернення (`routes_refund_requests.py:60-63`) —
    `(status != STATUS_NEW), created_at.asc()`: це робоча черга, нові зверху,
    далі найдавніші. Не «найновіші першими».
  - відгуки (`routes_reviews.py:43`) — `sort_order, created_at.desc()`:
    `sort_order` керує порядком публічного блоку на Головній.
  - B2B і заявки на курси — `created_at.desc()`.
- **Пагінація не має губити зріз.** `pager` отримує `filter_args`; чіпси й
  «Скинути все» вже працюють через макрос і лишаються як є.
- `empty_state` на всіх чотирьох сторінках уже викликається правильно
  (`b2b_requests.html:86`, `course_requests.html:180`,
  `refund_requests.html:153`, `reviews.html:154`) — не переписувати.
- **`course_requests.html:179`** має саморобний
  `{% set has_filters = filters.values() | select | list | length > 0 %}`.
  Перевірити, чи він ще потрібен після появи `per_page` у `filters`: з
  непорожнім `per_page` він став би істинним завжди. Якщо він керує показом
  чогось — виправити або прибрати; мовчки лишати не можна.
- **Ніколи `git add -A` чи `git add .`.** У цьому ж дереві працюють інші
  сесії Claude і мають незакомічену роботу. Стейджити лише свої файли
  поіменно. **`git stash` не використовувати** — воно робить стан дерева
  нечитним для інших сесій.
- **`python -m pytest tests/ -q` запускати НА ПЕРЕДНЬОМУ ПЛАНІ**, з таймаутом
  близько 600000 мс. Не в фоні, не через монітор, не опитуванням. На
  минулому плані два агенти згаяли на цьому по кілька ходів.
- Падіння всередині незакомічених файлів інших сесій
  (`tests/test_routes/test_admin_*_links.py`, `tests/test_seo/*`) — не наші:
  назвати їх і йти далі. Базова лінія на закоміченому коді — **2650 passed,
  1 xfailed**.
- **Тести прибирають за собою.** Тестова БД — спільна на сесію SQLite
  in-memory без робочих каскадів. Видаляти створене в autouse-фікстурі,
  дітей перед батьками. Тести, що створюють `User` через
  `create_with_password` + `commit()`, мусять чистити `User`, `AuthIdentity`
  і `MedicalProfile`, інакше падає
  `tests/test_routes/test_api_v1_clients.py::TestParticipants` — і лише в
  повному прогоні, зі `StopIteration` замість assert. Взірець:
  `tests/test_routes/test_admin_online_listings.py:30-58`.
- Без емодзі. Без inline-стилів і inline-скриптів. Без нових CSS-класів.
- Коментарі й рядки інтерфейсу — українською, як у решті адмінки.
- Коміти просто в `main`, без гілок і без пушу.

## Task 1: пагінація на всіх чотирьох сторінках (одним заходом)

Це чотири однакові за формою правки, тож вони робляться і рев'юються як одна
одиниця, а не як чотири задачі.

**Файли:**
`app/admin/routes_b2b_requests.py`, `app/templates/admin/b2b_requests.html`,
`app/admin/routes_course_requests.py`, `app/templates/admin/course_requests.html`,
`app/admin/routes_refund_requests.py`, `app/templates/admin/refund_requests.html`,
`app/admin/routes_reviews.py`, `app/templates/admin/reviews.html`,
`tests/test_routes/test_admin_inbound_pagination.py` (новий).

Для КОЖНОЇ з чотирьох сторінок:

1. У функцію фільтрів додати
   `'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES)`.
   У B2B, заявках на курси і поверненнях фільтри живуть у власному хелпері
   (`_b2b_filters`, `_course_request_filters`, `_filters`), і ЦЕЙ ЖЕ хелпер
   кличе експорт — тож `per_page` потрапить і туди. Це нешкідливо (експорт
   його не читає), але переконатись, що він не поїхав в аркуш «Фільтри»
   xlsx як нібито зріз: у `export_summary` його бути не повинно.
2. У роуті СТОРІНКИ замінити `.all()` на
   `.paginate(page=request.args.get('page', 1, type=int), per_page=_listing.per_page_arg(), error_out=False)`.
   У шаблон передати `pagination` і список як `pagination.items` під тим
   самим іменем, що й зараз (`requests` / `reviews`), щоб таблиця не
   переписувалась.
3. У роут експорту НЕ ЧІПАТИ нічого.
4. У `filter_bar` додати останнім полем
   `{'name': 'per_page', 'label': 'Рядків на сторінці', 'placeholder': '50 (типово)', 'options': per_page_options}`,
   передавши `per_page_options=_listing.PER_PAGE_OPTIONS` з роута.
5. Під таблицею додати `{{ pager('<endpoint>', pagination, filter_args) }}`,
   імпортувавши `pager` з макроса. Ендпоінти: `admin.b2b_requests_list`,
   `admin.course_requests_list`, `admin.refund_requests_list`,
   `admin.reviews_list`.
6. Порядок сортування не міняти (див. Global Constraints).

Окремо: розібратись із `course_requests.html:179` (`has_filters`) за
Global Constraints.

**Тести** — новий файл `tests/test_routes/test_admin_inbound_pagination.py`.
На КОЖНУ з чотирьох сторінок:

- більше за одну сторінку записів: перша сторінка віддає рівно `per_page`
  рядків, друга — решту, і рядки не повторюються;
- `?page=2` разом з активним фільтром зберігає фільтр у посиланнях
  пагінатора;
- `?per_page=25` справді дає 25 рядків, а сміття (`?per_page=99999`)
  відкочується на типове значення;
- **експорт віддає ВЕСЬ зріз, а не сторінку** — окремий тест на кожну з
  трьох сторінок з експортом (B2B, заявки на курси, повернення): створити
  більше записів, ніж уміщує сторінка, і перевірити кількість рядків у
  xlsx. Це головний тест цього плану.
- лічильники (`new_count` у B2B і поверненнях) не змінюються від переходу на
  другу сторінку.

Порядок для заявок на повернення перевірити окремо: новий запис мусить бути
на першій сторінці навіть якщо він найдавніший за датою.

## Task 2: повний прогін і звірка

1. `python -m pytest tests/ -q` — увесь набір. Порівняти з базовою лінією
   2650 passed, 1 xfailed; падіння в незакомічених файлах інших сесій
   назвати поіменно.
2. `python tools/ds/ds_audit.py` — переконатись, що нових дублікатів класів і
   сиріт не з'явилось.
