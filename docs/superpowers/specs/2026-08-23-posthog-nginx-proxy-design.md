# PostHog через first-party nginx-проксі

Дата: 2026-08-23
Статус: затверджено до реалізації

## Мета

Додати PostHog (product analytics + session replay) до site-iprm так, щоб
запити йшли через власний домен і не різались блокувальниками -- тим самим
прийомом, яким уже віддається GA4 (`/ngx-i/`).

Проєкт PostHog: **IPRM**, id `255460`, EU Cloud, токен
`phc_wi73dtG77zD6oQua7i8xFERD9CYDqHYac9xcRBvEMKof`.
Токен `phc_*` -- публічний ідентифікатор, він і так їде у HTML кожної
сторінки; секретом не є і шифрування не потребує.

## Рішення власника

| Питання | Рішення |
|---|---|
| Продукти | pageviews + autocapture, власні події з форм, session replay, heatmaps, web vitals |
| Ідентифікація | `identify` разом з email |
| Периметр | скрізь, включно з адмінкою |
| Префікс проксі | `/ngx-e/` |

Реплей і адмінка -- свідомий вибір власника. Запобіжники нижче (маскування,
окремий рубильник, `iprm_section`) не звужують цей вибір, а роблять його
оборотним і придатним для фільтрації.

## Архітектура

### 1. nginx (`deploy/nginx/snippets/iprm-app.conf`)

PostHog розводить трафік по ДВОХ апстрімах, тому потрібні ТРИ location-блоки:

| Шлях | Апстрім | Нащо |
|---|---|---|
| `/ngx-e/static/` | `eu-assets.i.posthog.com` | SDK (`array.js`), `recorder.js` |
| `/ngx-e/array/` | `eu-assets.i.posthog.com` | ремоут-конфіг SDK |
| `/ngx-e/` | `eu.i.posthog.com` | події, флаги, записи сесій |

Обов'язкові умови (з доки PostHog):

- `Host` виставляється на апстрім-домен, інакше PostHog віддає **401**.
- `X-Forwarded-For` прокидається -- по ньому визначається гео. На відміну
  від GA-проксі, геолокація тут НЕ ламається.
- `client_max_body_size 64m` на api-локації: записи сесій великі, а в
  сніпеті глобально стоїть 25m.
- `/ngx-e/array/` -- `no-store`. У PostHog відкритий баг (#40619), де
  закешований 301 на ротованому IP ламає конфіг назавжди для браузера.

Хости апстрімів -- ТІЛЬКИ через `set $...`, ніколи буквально в `proxy_pass`.
Буквальний хост змушує nginx резолвити DNS на старті й відмовлятись
стартувати при збої DNS -- саме так сайт ліг 29.07.2026. `resolver` уже
оголошений у сніпеті для GA, повторно не дублюємо.

Назва префікса: дока PostHog прямо попереджає не брати `/posthog`, `/ph`,
`/analytics` -- блокувальники ловлять їх за назвою. `/ngx-e/` тримає той
самий непрозорий стиль, що й наявний `/ngx-i/`.

### 2. CSP (`app/__init__.py`)

Оскільки весь трафік іде через власний домен, `'self'` покриває запити.
АЛЕ session replay створює Web Worker з `blob:` для стиснення. Директиви
`worker-src` зараз немає взагалі, тож вона впаде на `default-src 'self'`
і реплей мовчки не запрацює. Додаємо `worker-src 'self' blob:` умовно.

`ui_host` (`https://eu.posthog.com`) додається до `script-src`/`connect-src`
лише коли інтеграція активна -- для тулбара.

### 3. Модель + міграція

```
posthog_enabled            Boolean  default False
posthog_project_api_key    String(60) default ''
posthog_session_recording  Boolean  default False
```

Окремий прапорець реплею -- не надмірність: на сайті з медданими вимкнути
саме запис екрана треба вміти миттєво, не стираючи ключ і не гасячи всю
аналітику.

Семантика пари `enabled`+ключ дзеркалить Meta Pixel, а не GA: якщо ключ
заданий у БД, саме прапорець БД вирішує, і env не підміняє вимкнення
(інакше пастка "вимкнув в адмінці, а воно й далі шле").

### 4. Сервіс `app/services/posthog.py`

`active_posthog_config(settings=None)` -> dict або None. Одна функція, яку
питають І шаблон (чи вставляти скрипт), І CSP (чи дозволяти домени). Тримати
умову в двох місцях означає, що вони розійдуться, і найгірший варіант тихий:
CSP пускає домени там, де скрипта вже немає.

Повертає: `api_host`, `ui_host`, `project_api_key`, `session_recording`,
`section` (блупринт поточного запиту), `mask_all_text` (True в адмінці).

### 5. Фронтенд

- `app/static/js/posthog.js` -- черга-заглушка + ліниве вантаження SDK
  після `load` / першої взаємодії / стелі таймера. Точно як `analytics.js`
  для gtag: виклики до приходу лоадера чекають у черзі й програються.
- `app/static/js/posthog-events.js` -- читає НАЯВНІ `data-ga-event` і
  `data-ga-event-load`. Жодного нового розмічування шаблонів.
- `app/templates/partials/_posthog.html` -- лише `<script>` з data-атрибутами
  (CLAUDE.md: No Inline Policy).

### 6. Приватність

- `mask_all_element_attributes` + `maskAllInputs: true` -- значення полів
  (ПІБ, телефон, медпрофіль) не йдуть ні в autocapture, ні в реплей.
- В адмінці реплей маскує ВЕСЬ текст (`maskTextSelector: '*'`): лишаються
  кліки й навігація, зникає відео карток учасників.
- `iprm_section` (блупринт) у кожній події -- дозволяє відфільтрувати
  адмінку в PostHog одним кліком, без правки коду.

### 7. Адмінка / докси / тести

- `app/admin/routes_posthog.py` + `app/templates/admin/posthog.html`
- `_check_posthog` в `integration_health.py`, картка в `integrations.html`
- запис у `EXPORTABLE` (`integration_config_io.py`)
- `docs/integrations/posthog.md`, розділ у `docs/deployment.md`
- `tests/test_routes/test_posthog.py`

## Порядок деплою

1. nginx-локації (без коду просто не використовуються)
2. міграція
3. код
4. перевірка: `curl -sI https://plasma-regen.com/ngx-e/static/array.js` -> 200

Зворотний порядок дає вікно, коли `/ngx-e/static/array.js` віддає 404.

## Поза обсягом

- Server-side події (PostHog Python SDK) -- окрема задача.
- Feature flags / experiments -- SDK їх підтягне, але в коді не вживаємо.
- Оновлення політики конфіденційності -- на власнику; реплей і email у
  сторонньому процесорі цього вимагають.
