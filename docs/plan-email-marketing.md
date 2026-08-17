# План: платформа email-маркетингу (mm-medic + ІПРМ)

Дата: 2026-08-13. Статус: чернетка на погодження.

Документ описує, де саме будувати систему розсилок, як розділити відповідальність
між материнським проєктом mm-medic і дочірнім ІПРМ, і в якому порядку це робити.

Позначення шляхів: `app/...` без префікса - це ІПРМ (`D:\site-iprm`);
шляхи mm-medic позначені явно як `[MM] app/...` (`D:\site-mm-medic`).

---

## 1. Рішення: платформа живе в mm-medic

Розвідка обох кодових баз дала однозначну відповідь.

### Що вже готове в mm-medic

| Підсистема | Стан | Файл |
|---|---|---|
| Асинхронна відправка | працює в проді | [MM] `app/services/email/` (40 файлів), Celery `email.send_single` |
| Черга з пріоритетами | працює | [MM] `app/models/email_models.py:89` (`EmailQueue`), 4 черги `email.urgent/high/normal/low` |
| Celery Beat | працює, 9 email-задач | [MM] `app/tasks/config.py:753+` (диспетчер кожні 30 с) |
| Rate limiting | працює, Redis | [MM] `app/services/email/rate_limiter.py` (20/год і 50/добу на адресу, 200/хв глобально) |
| Згода і відписка | працює, централізовано | [MM] `app/services/email/consent_policy.py`, `UserEmailPreferences` (`email_models.py:521`) |
| Публічні сторінки відписки | працюють | [MM] `app/blueprints/main/email_routes.py:21` |
| Моделі розсилок | є | [MM] `app/models/mailing.py` (`Mailing`, `MailingRecipient`, `MailingLog`) |
| Адмін-UI розсилок | є, 14 роутів | [MM] `app/blueprints/admin/routes/marketing_mailings.py` |
| Rules-engine тригерів | працює, 17 тригерів | [MM] `app/models/notification_system.py`, `app/services/notifications/notification_service.py` |
| CRM-таймлайн клієнта | працює, 8 джерел | [MM] `app/services/salesops/timeline_service.py`, вкладка «Листи» в профілі |
| Дзеркало ІПРМ | працює | [MM] `app/models/iprm_catalog.py`, зшивання клієнтів `app/services/iprm/identity.py:7` |

### Що є в ІПРМ

SMTP-відправка, `EmailLog`, suppression-список, відписка через `List-Unsubscribe`,
дані для сегментації (спеціалізації, реєстрації, оплати) і транзакційні шаблони.
Черги, трекінгу, моделей кампаній і CRM-стрічки немає.

### Наслідок

Будувати платформу в ІПРМ означало б написати з нуля Celery-конвеєр, трекінг,
згоди, сегменти і таймлайн - тобто продублювати те, що в mm-medic уже стоїть.
Менеджери працюють у `https://mm-medic.com/uk/admin/`, і клієнтська картка з
історією дотиків уже там.

**Розподіл відповідальності:**

- **mm-medic** - редактор листів, сегменти, відправка, трекінг, аналітика,
  тригерні сценарії, картка клієнта з усіма дотиками.
- **ІПРМ** - транзакційні листи (реєстрація, оплата, нагадування, сертифікат)
  лишаються на місці; ІПРМ постачає дані для сегментів, посилання для змінних,
  події реального часу і дзеркалить власні листи в mm-medic як дотики.

Переносити транзакційні листи ІПРМ у mm-medic не пропонується: вони жорстко
зчеплені з бізнес-логікою реєстрації й оплати, мають власні шаблони, локалізацію
і suppression. Дублювати цей ланцюг через партнерське API - зайвий ризик.

---

## 2. Фаза 0. Блокери в mm-medic

Без цієї фази жодна розсилка фізично не вийде. Роботи тут менше, ніж здається,
бо більшість коду вже написана - її треба підключити й полагодити.

### 0.1. Розсилки не відправляються

[MM] `app/blueprints/admin/routes/marketing_mailings.py:457-459`:

```python
# TODO: Trigger actual email sending task (e.g., Celery task)
# from app.tasks import send_mailing_task
# send_mailing_task.delay(mailing.id)
```

`/send` створює `MailingRecipient` зі статусом `pending`, ставить
`Mailing.status='sending'` - і на цьому все. Жодна Celery-задача не читає
таблиці `mailings`. Лічильники `sent_count`/`opened_count`/`clicked_count`
ніколи не інкрементуються.

Поруч лежить готовий і не підключений сервіс [MM] `app/services/mailing_service.py`
(~1100 рядків): `send_mailing():375` з батчами по 50 і `test_mode`,
`prepare_recipients():280`, `process_scheduled_mailings():524`,
`update_statistics():561`, `_send_to_recipient():889` через `EmailQueueService`,
`_log_mailing_event():1011`. Жоден файл проєкту його не імпортує.

**Дія:** створити Celery-задачу `mailing.send` (черга `email.low`, маршрут у
`app/tasks/config.py`), підключити до неї наявний сервіс, замінити TODO на
`send_mailing_task.delay(mailing.id)`. Задепрекейтити дві мертві копії тієї
самої логіки: [MM] `app/services/marketing/mailing_service.py` та інлайн-вибірку
отримувачів у роуті (`marketing_mailings.py:400-430`).

### 0.2. Розсилки обходять згоду - юридичний ризик

`mailing_send` шле «всім верифікованим» (`User.email_verified_at IS NOT NULL`)
плюс два прапорці `verified_only`/`active_only`. Ні `UserEmailPreferences`, ні
`UserProfile.newsletter_subscribed`, ні `consent_policy.can_send_to_user()` не
перевіряються. Тобто відписаний користувач отримає розсилку.

**Дія:** провести вибірку отримувачів через `can_send_to_user()`, зареєструвати
шаблони розсилок у `CONSENT_GATED_TEMPLATES` ([MM] `consent_policy.py:64-73`).
Це треба зробити **до** першої реальної розсилки, а не після.

### 0.3. Трекінг не існує

- URL генеруються ([MM] `app/services/email/template_service.py:723-752`):
  `{SITE_URL}/api/email/track/open/{email_log_id}` і `/api/email/track/click/{id}?url=...`
- Роутів `/api/email/track/*` у проєкті **немає**.
- `EmailTracking` - порожня таблиця; `TrackingAdapter.track_event()` не викликається ніде.
- `TrackingService` зламаний: звертається до `EmailEventType.OPEN/CLICK/BOUNCE`,
  тоді як в енумі `OPENED/CLICKED/BOUNCED`; пише в неіснуючі поля
  `total_opens`/`total_clicks`/`bounced_at`.
- **Баг у кожному листі:** [MM] `template_service.py:197` кладе в контекст саму
  функцію замість рядка (`full_context['tracking_pixel_url'] = self._get_tracking_pixel_url`).
  У Jinja функція truthy, тож `layout.html:235` рендерить
  `<img src="<bound method...>">`. Це зараз їде в кожному листі з mm-medic.

**Дія:**
1. Полагодити `template_service.py:197` (виклик функції, не посилання на неї).
2. Виправити енуми й поля в `TrackingService`.
3. Додати два роути: `GET /api/email/track/open/<id>.png` (1x1 GIF/PNG,
   `Cache-Control: no-store`) і `GET /api/email/track/click/<id>`.
4. **Клік-редирект тільки на URL із whitelist кампанії.** Приймати довільний
   `?url=` - це open redirect, яким користуються для фішингу з довіреного домену.
   Зберігати перелік посилань листа при рендері і редиректити за індексом.
5. Заповнювати `EmailLog.opened_at/first_clicked_at/unique_opens/unique_clicks`
   і `MailingRecipient.opened_at/clicked_at`.

### 0.4. Немає bounce-обробки і suppression-списку

Невалідна чи відбита адреса нікуди не заноситься і буде використана знову.
`bounced_count`, `bounce_rate` завжди нуль. Це прямий удар по репутації домену.

**Дія:** таблиця suppression за зразком ІПРМ ([app/models/email_suppression.py](app/models/email_suppression.py))
з причинами `bounce`/`unsubscribe`/`complaint`; IMAP-обробник відбиття за зразком
[app/services/bounce_service.py](app/services/bounce_service.py); перевірка
suppression перед постановкою в чергу.

### 0.5. UTM у листах немає

`UTMService` ([MM] `app/services/utm_service.py:29`) працює лише на вхідний
трафік. У всьому email-коді й шаблонах жодного `utm_*`.

**Дія:** хелпер розмітки посилань у контексті рендера, за зразком
[app/services/email_service.py:441](app/services/email_service.py#L441).
Схема: `utm_source=email`, `utm_medium=email`, `utm_campaign=mailing-<id>`,
`utm_content=<блок листа>`. Це фундамент аналітики конверсій (Фаза 6).

**Обсяг Фази 0:** переважно підключення й лагодження наявного коду.

---

## 3. Фаза 1. Сегменти (пункт 1 вимог)

### Поточний стан

Логіка вибірки отримувачів існує в **трьох розбіжних копіях**:
[MM] `mailing_service._get_filtered_users():757`, `mailing_service.calculate_recipients():187`
і інлайн у роуті `marketing_mailings.py:400`. Набори ключів у них різні.

Фільтри в UI не працюють: шаблон `mailing_edit.html:226+` читає неіснуючий
атрибут `mailing.filters`, тоді як на моделі поле зветься `recipient_filter`.
Значення завжди порожні, а при відправці читаються лише `verified_only`/`active_only`.

Типи отримувачів (`doctors/distributors/patients`) побудовані на
`UserProfessionalData.user_type`, яке заповнене **у 14 записах із 3346**.
Тобто наявна сегментація фактично не працює.

### 1.1. Єдиний компілятор сегментів

Модель `Segment(name, definition JSONB, is_dynamic, owner_id)` і **одна** функція
`definition -> SQLAlchemy query`. За основу взяти [MM] `app/services/salesops/lead_query.py:90`
(`apply_filters`) - вона вже вміє тристани `yes/no/unknown`, `'none'` для «без
менеджера», `stale_days` від `last_interaction_at`, екранований пошук.
Розширити до N предикатів з AND/OR.

Перевести `Mailing.recipient_filter` на компілятор і видалити три дублі.

### 1.2. Спеціалізації - спільний довідник

У mm-medic класифікатора немає: `UserProfessionalData.specialization` - вільний
рядок String(100) без індексу, довідник `SPECIALIZATIONS` порожній. З ІПРМ
приїжджає **лише перший елемент списку** і **лише в порожнє поле**
([MM] `app/services/iprm/identity.py:331-357`). Паралельно існує
`IprmRegistration.specialty` - текстовий знімок анкети, не звірений із першим полем.

**Дія:** перенести 78 кодів з [app/models/specializations.py](app/models/specializations.py)
у довідник mm-medic; таблиця `user_specializations` (M2M) замість обрізаного
рядка; бекфіл із двох джерел; ІПРМ віддає `specialization_labels` (Фаза 3).

### 1.3. Гео

Нормалізованого гео немає в жодному проєкті. У mm-medic `UserProfile.city` -
вільний текст без довідника; `region` є лише в `UserAddress`, тобто лише в тих,
хто оформляв доставку. `app/regions.py` до цього стосунку не має (це профіль
інстансу UA/KZ).

**Мінімальний варіант без міграції даних:** похідне гео - місто останнього
заходу, на який людина реєструвалась (`IprmEvent.city` уже структуроване).
**Повний варіант:** довідник областей + нормалізація міст + денормалізація на профіль.

### 1.4. Сегмент «не відкрив попередню хвилю»

Це прямо ваш сценарій. Реалізується запитом по `MailingRecipient` попередньої
кампанії: `opened_at IS NULL AND status = 'sent'`. Передумова - Фаза 0.3
(без трекінгу поле завжди порожнє, і сегмент дасть усіх).

### 1.5. Імпорт контактів з xlsx

Сторінка `/import-export/users` існує, **бекенда немає**. Є повноцінна абстрактна
база [MM] `app/services/base_import_export_service.py:30` (`validate_headers`,
`parse_row_by_headers`, `import_from_xlsx`, `generate_template_xlsx`),
реалізована для товарів/заходів/замовлень. Додати реалізацію для контактів.

---

## 4. Фаза 2. Редактор листів (пункт 2 вимог)

Зараз HTML розсилки редагується сирим `<textarea>` ([MM] `mailing_edit.html:181-184`).

### 2.1. CKEditor 5

Вендорити локально (без CDN), підключити в `mailing_edit.html`. Панель обмежити
тим, що переживає поштові клієнти: заголовки, списки, посилання, картинка,
таблиця, готові блоки-сніпети. Outlook не підтримує flex/grid, тож верстка -
таблична, за зразком [MM] `app/templates/email/base/components.html`.

Ліцензія: CKEditor 5 - GPL2+ для open-source використання; у self-hosted
складання новіших версій потрібен `licenseKey: 'GPL'`.

### 2.2. Змінні (пункт 4 вимог)

| Змінна | Джерело |
|---|---|
| `{{ first_name }}`, `{{ last_name }}` | `UserProfile` |
| `{{ course_title }}` | дзеркало `IprmCourse`/`IprmEvent` |
| `{{ course_start }}` | `IprmEvent.start_date` |
| `{{ course_url }}` | `detail_url` з API ІПРМ (уже віддається) |
| `{{ pay_url }}` | **треба додати в API ІПРМ** - Фаза 3 |
| `{{ gcal_url }}` | **треба додати** - `calendar_service.google_calendar_url` існує |
| `{{ ics_url }}` | **треба додати роут** - `build_ics` існує |
| `{{ unsubscribe_url }}` | `UserEmailPreferences.get_or_generate_token()` |

Рендер - `SandboxedEnvironment` (уже застосований у прев'ю,
`marketing_mailings.py:570`). Довільний Jinja-рендер рядка з БД без пісочниці
дав би виконання коду з адмінки.

### 2.3. Санітизація

Whitelist під email: теги плюс `style` на всіх елементах і табличні атрибути
(`bgcolor`, `align`, `valign`, `cellpadding`, `cellspacing`, `border`, `width`).
Обов'язково `bleach.css_sanitizer.CSSSanitizer` - інакше bleach 5+ ріже весь `style`,
і від дизайну листа нічого не лишиться.

---

## 5. Фаза 3. ІПРМ як постачальник даних

Наявне API: `/api/v1/events`, `/events/<slug>`, `/participants`, `/registrations`,
`/leads` з курсором `updated_since` і ключем `X-API-Key`. Що треба додати:

### 3.1. `/participants` - поля для сегментації

| Поле | Навіщо | Де лежить |
|---|---|---|
| `preferred_language` | якою мовою слати | [app/models/user.py:27](app/models/user.py#L27) |
| `email_opt_out`, `unsubscribe_url` | **критично** - зараз mm-medic не знає, хто відписався на ІПРМ | [app/models/user.py:32](app/models/user.py#L32) |
| `email_deliverable` | синтетичне поле, інкапсулює `_will_be_delivered()` разом із bounce-станом | [app/services/email_service.py:588](app/services/email_service.py#L588) |
| `last_login_at` | сегмент «сплячі» | колонка вже є |
| `registrations_count`, `last_registration_at`, `last_paid_at`, `total_paid_amount`, `attended_count` | активність без повного обходу `/registrations` | агрегати |
| `specialization_labels` | інакше mm-medic хардкодить мапінг кодів | метод `MedicalProfile.specialization_labels` існує |
| `last_event_city` | похідне гео | `CourseInstance.city` |

### 3.2. Фільтри на `/participants`

`specialization=`, `city_id=`, `participant_type=`, `opt_out=false`, `active_since=`.
Зараз можлива лише повна вивантажка (1264+ записів сторінками по 100) з
фільтрацією на боці партнера.

### 3.3. Довідник спеціалізацій

`GET /api/v1/specializations` - щоб mm-medic не хардкодив 78 кодів і не
розходився при кожному додаванні.

### 3.4. Посилання для змінних

Збагатити `serialize_instance` (зараз він бідніший за картку курсу - немає ні
`title`, ні `detail_url`, ні тренера): додати `pay_url` (логіка
`EmailService._pay_url_for_registration` враховує гостьовий `completion_token`),
`gcal_url`, `ics_url`, `account_url`.

Новий роут `GET /api/v1/instances/<id>/calendar.ics` - HTTP-обгортка над готовим
`build_ics` з [app/services/calendar_service.py](app/services/calendar_service.py).
UID у ньому стабільний, тож повторний лист оновлює подію, а не дублює її.

### 3.5. Стабільний тайбрейкер

`app/api/v1/clients.py:103` сортує лише за `updated_at` без `id`, хоча коментар
обіцяє інше. При масовому імпорті з однаковим `updated_at` рядки «плавають» між
сторінками і інкрементальна синхронізація їх губить. Виправити на
`order_by(updated_at, id)`.

### 3.6. UTM

Приймати `?utm_campaign=` і повертати вже розмічені URL, перевикориставши
[`_with_utm`](app/services/email_service.py#L441). Одна реалізація мітки на два
проєкти замість двох розбіжних.

### 3.7. Rate limiting

Ліміти рахуються за IP (`get_remote_address`), не за API-ключем; поверх іменованих
лімітів діє дефолтний `200 per hour`. При переході на частіший pull це вистрелить.
Плюс `RATELIMIT_STORAGE_URI` у проді має бути Redis - на `memory://` ліміти
множаться на кількість gunicorn-воркерів.

---

## 6. Фаза 4. Події реального часу ІПРМ -> mm-medic

Зараз mm-medic дізнається про реєстрації й оплати **лише pull-ом** раз на цикл
крона. Вихідні вебхуки ІПРМ існують тільки про курси.

### 4.1. Узагальнити чергу вебхуків

`webhook_deliveries` жорстко прив'язана до курсів: `course_id`/`course_slug`
`NOT NULL`, CHECK `action IN ('created','updated','deleted')`, тіло не
зберігається, а щоразу перебудовується з трьох колонок.

**Дія:** додати `event_type` і `payload` (JSON), зробити `course_id` nullable,
послабити CHECK, змінити сигнатуру `dispatch_one`.

### 4.2. Нові події

`registration.created`, `registration.paid`, `registration.cancelled`,
`registration.attended`.

Точки enqueue:
- [app/registration/routes.py:400-422](app/registration/routes.py#L400) - публічний чекаут, після коміту;
- [app/services/participant_service.py:274](app/services/participant_service.py#L274) - менеджер додав учасника;
- [app/services/payment_ops.py](app/services/payment_ops.py) - у гілці `new_status == 'paid'`,
  поруч із `send_payment_confirmation`. Через `update_payment_status` проходять
  **усі** джерела: LiqPay-callback, polling, ручна зміна, повернення.

**Пастка:** безкоштовні реєстрації отримують `paid` усередині
`registration_service.create_or_reactivate`, повз `payment_ops`. Хук лише на
`payment_ops` їх пропустить.

### 4.3. Окремі гейти

`partner_webhook_enabled` зараз один на все. Потрібна підписка за типами подій,
щоб увімкнення реєстраційних подій не тягло за собою курсові й навпаки.

### 4.4. Уніфікувати підпис

Вихідні вебхуки підписують `HMAC(secret, body)` без timestamp - **replay-захисту
немає**. Вхідний канал `mm_status.py` уже використовує сильнішу схему
`HMAC(secret, "<ts>.<body>")` + `X-IPRM-Timestamp` з вікном 300 с. Перевести
вихідні на неї, версіонувавши заголовком заради зворотної сумісності.

### 4.5. Бік mm-medic

Вхідний вебхук [MM] `app/blueprints/events/routes.py:513` **ігнорує `event_type`** -
він використовується лише в логах, а будь-яка подія запускає повний pull-sync
каталогу. Дедуп - тільки в Redis з fail-open (при недоступності Redis подія
обробляється двічі).

**Дія:** роутинг за `event_type` зі збереженням зворотної сумісності для `event.*`;
durable-журнал вхідних подій через наявну модель `WebhookRequest`
([MM] `app/models/webhook_request.py:20`) замість Redis-only дедупу. Для
комунікацій, де кожне відкриття - окрема подія, а не стан, fail-open означав би
подвійний облік.

**Альтернатива, чистіша:** винести нові події в окремий
`POST /api/partner/iprm/events` з наявним декоратором `require_iprm_hmac` - без
мовного префікса, з replay-захистом і готовими тестами.

---

## 7. Фаза 5. Дотики ІПРМ у картці клієнта (головна вимога)

### 7.1. ІПРМ пушить комунікації

Подія `communication.sent` на кожен перехід `EmailLog` у `sent`/`failed`.
Payload: зовнішній id, email, `template_key`, тема, статус, час.

**Пастка:** листи часто шлються зі scheduler-джоб **без app context**. Наївне
копіювання патерну з [app/services/course_webhook_listener.py:93-102](app/services/course_webhook_listener.py#L93)
тихо губитиме події - там enqueue пропускається саме за відсутності контексту.
Це найризикованіше місце фази.

Поважати `EmailLog.OPTIONAL_TRIGGERS`, `email_opt_out` і suppression: не
пересилати партнеру те, від чого клієнт відписався.

### 7.2. mm-medic зберігає

Таблиця `iprm_communications` (`external_id` unique, `user_id`, `to_email`,
`template_key`, `subject`, `status`, `sent_at`, `opened_at`, `clicked_at`) +
`iprm_communication_events` (`event_type`, `event_data` JSONB, `occurred_at`,
unique по трійці для природної ідемпотентності).

Структуру копіювати з наявних [MM] `email_models.py:259` (`EmailLog`) і `:450`
(`EmailTracking`) - словник подій `EmailEventType` уже містить рівно потрібні
значення: `queued/sent/delivered/opened/clicked/bounced/complained/unsubscribed`.

### 7.3. Зшивання з клієнтом

Через готовий ланцюг `User.iprm_user_id` -> `IprmUserAlias` -> [MM] `identity.py`
(телефон головний, потім справжня пошта; технічні адреси `@noemail.invalid`,
`@xlsx.temp` збігом не рахуються; збіг лише за ПІБ не зшиває - тезки).
Нового matching-механізму не треба.

### 7.4. Показ у профілі

Таймлайн у mm-medic - це **read-model, а не таблиця**: [MM] `timeline_service.py`
зводить 8 джерел. Додати дев'яте:

1. `TimelineKind.IPRM` у перелік і в `ALL` (`timeline_service.py:40-51`);
2. запис у `RESTRICTED` (`:56-62`);
3. loader `_iprm(user_id, limit)` за зразком `_mailings():265`;
4. реєстрація в `_LOADERS` (`:361-370`);
5. `allowed.discard(TimelineKind.IPRM)` без права ([MM] `interactions.py:144-162`).

У шаблоні профілю - **одна кнопка-фільтр** у наявний ряд вкладок
([MM] `app/templates/admin/users/detail.html`, після вкладки «Листи»), бо вкладки
6-10 це не окремі панелі, а фільтри однієї стрічки. Панель, пагінатор, порожній
стан, `aria-live` перевикористовуються як є.

Інваріант, який треба поважати: **тіла листів у стрічку не входять** - запис
відповідає на «коли писали», вміст живе у скриньці.

### 7.5. Зворотний канал відписки

`POST /api/v1/participants/<id>/opt-out` в ІПРМ - щоб відписка з листа mm-medic
виставляла `email_opt_out` в ІПРМ. Інакше згоди двох систем розійдуться, і людина,
яка відписалась в одній, отримуватиме листи з іншої. Це і юридична, і репутаційна
проблема.

---

## 8. Фаза 6. Аналітика (пункт 3 вимог)

| Метрика | Джерело | Передумова |
|---|---|---|
| Надіслано | `MailingRecipient.status` | Фаза 0.1 |
| Доставлено | статус SMTP | Фаза 0.1 |
| Відкрито | піксель | Фаза 0.3 |
| Кліки | редирект | Фаза 0.3 |
| Реєстрація | UTM -> реєстрація в ІПРМ -> `/registrations` -> зіставлення з `MailingRecipient` | Фаза 0.5 + 3.6 + нове поле `EventRegistration.utm_campaign` в ІПРМ |
| Покупка | те саме, по `payment_status='paid'` | те саме |
| Живий email | MX-перевірка + suppression | Фаза 0.4 |

Про «живий email»: валідатор [MM] `app/utils/email_validators.py` уже вміє MX-перевірку,
disposable-домени й підказки друкарських помилок, але в проді її **вимкнено**
(`EmailValidator(check_deliverability=False)`, `base_mixin.py:76`). Увімкнути для
масових розсилок (не для транзакційних - там затримка DNS зайва), додати
періодичну верифікацію бази.

Хибні очікування, які варто зафіксувати: open rate занижений через блокування
пікселів (Apple Mail Privacy Protection навпаки завищує), тож єдина надійна
метрика для рішень - кліки й конверсії.

Дашборд кампанії будувати на наявних hybrid-властивостях `Mailing.open_rate`,
`click_rate`, `bounce_rate`, `delivery_rate` (`app/models/mailing.py:65-92`).

---

## 9. Фаза 7. Тригерні автоматизації (пункт 5 вимог)

Основа вже є: ANS - справжній rules-engine `trigger -> conditions(JSON) ->
recipient_group -> template` з `delay_minutes`, аудит-трейлом, ретраями,
per-rule SAVEPOINT-ізоляцією і готовим адмін-UI CRUD правил
([MM] `app/blueprints/admin/routes/notifications.py:274`). Засіяно 17 тригерів.

**Що додати:**

1. Тригери від подій ІПРМ (Фаза 4): `iprm.registration.created`,
   `iprm.registration.paid`, `iprm.registration.cancelled`, `iprm.event.reminder`.
2. `RecipientGroup` типу `segment` з посиланням на сегмент із Фази 1. Зараз група
   вміє лише роль / статичний список / поле з `event_data` - для маркетингових
   тригерів це блокер.
3. Розширити `matches_conditions` ([MM] `notification_system.py:357-396`): зараз
   лише плоскі ключі, лише AND, лише скалярні оператори. Треба `$in`, `$contains`, OR.
4. Багатокрокові сценарії: `Automation(trigger, segment_id, steps JSONB)` +
   `AutomationRun(user_id, current_step, next_run_at, state)`. Математика каденції
   готова в [MM] `app/services/salesops/cadence.py` (послідовність 0/3/7/14 днів,
   backoff x1.5, стеля 180) - її треба перенести з дзвінків на листи.
5. Frequency capping - скільки листів на людину за тиждень. Зараз немає.

**Обмеження, яке треба поважати:** [MM] `app/models/order.py:1680-1691` явно
забороняє асинхронні слухачі для критичних полів («асинхронні слухачі лишають
вікно розсинхронізації»). Нова подієва шина має це враховувати. Готовий шов для
збору подій - `after_commit` на `db.session`, уже налаштований у
[MM] `app/services/cache_invalidation.py:383`.

---

## 10. Рішення, потрібні до старту

### 10.1. Домен і відправник

mm-medic шле з `noreply@mm-medic.online` через `mail.adm.tools`. Розсилка про
курси ІПРМ з домену mm-medic - це питання і впізнаваності бренду, і
доставлюваності. Варіанти:

- окремий відправник для ІПРМ-розсилок (потребує SPF/DKIM для домену ІПРМ на
  тому ж поштовому шляху; DKIM-селектор ІПРМ - `hosting` на adm.tools);
- єдиний відправник mm-medic із явною згадкою ІПРМ у темі й шапці листа.

Зараз відправник у mm-medic **один** (`MAIL_DEFAULT_SENDER`), кілька не
підтримуються - це доробка.

Окремо: пароль SMTP лежить у `.env` відкритим текстом.

### 10.2. Єдина точка правди для згод

Дві бази, дві моделі згоди: `User.email_opt_out` в ІПРМ і `UserEmailPreferences`
(5 категорій) у mm-medic. Потрібне рішення, яка з них головна і як
синхронізуються відписки в обидва боки (Фази 3.1 і 5.5).

### 10.3. Спільний довідник спеціалізацій

78 кодів живуть в ІПРМ. У mm-medic - вільний текст. Треба вирішити, чи
переносити довідник у mm-medic, чи ІПРМ лишається джерелом правди й віддає
його через API.

### 10.4. Обсяг гео

Мінімальний варіант (місто останнього заходу) не потребує міграції даних.
Повний (довідник областей + нормалізація) - окрема робота з бекфілом.

---

## 11. Порядок робіт

| Крок | Що дає | Залежності |
|---|---|---|
| Фаза 0 | розсилки фізично працюють, трекінг збирається, згода не порушується | немає |
| Фаза 1.1-1.2 | сегменти замість трьох зламаних копій | 0 |
| Фаза 2 | CKEditor 5 і змінні | 0 |
| **Проміжний результат** | **менеджер робить розсилку з редактором, сегментами і статистикою** | |
| Фаза 3 | дані ІПРМ для сегментів і посилань | немає (можна паралельно) |
| Фаза 4 | події реального часу | 3 |
| Фаза 5 | дотики ІПРМ у картці клієнта | 4 |
| Фаза 6 | конверсії до реєстрації й покупки | 0.5, 3.6, 4 |
| Фаза 7 | тригерні сценарії | 1, 4 |

Фази 0-2 не залежать від ІПРМ узагалі - їх можна почати одразу.
Фаза 3 не залежить від mm-medic - її можна вести паралельно в ІПРМ.

---

## 12. Ризики

1. **Репутація домену.** Перша ж масова розсилка на кілька тисяч адрес без
   прогріву і без bounce-обробки псує репутацію надовго. Порядок: Фаза 0.4,
   потім маленький сегмент, потім масштабування.
2. **Спільна БД ІПРМ.** Локальний `.env` і прод дивляться в одну базу - будь-яка
   локальна команда б'є по проду. Розробку Фаз 3-5 вести з цим на увазі.
3. **Юридичний ризик уже існує** - розсилки в mm-medic обходять відписку.
   Фаза 0.2 не має відкладатись.
4. **Спільний HMAC-секрет.** Один `partner_webhook_secret` обслуговує три канали.
   Додавання комунікацій розширює зону ураження цього ключа на персональні дані
   листування. Варто розвести секрети або свідомо зафіксувати рішення.
5. **Мертвий код.** Три копії `MailingService`, зламаний `TrackingService`,
   заготовки `providers/` під SendGrid/SES. Перед доробкою - вирішити, що
   лишається, інакше наступний розробник знову напише четверту копію.
