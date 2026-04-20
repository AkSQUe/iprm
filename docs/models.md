# Модель даних

## User

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `email` | String(255) | Унікальний, індексований |
| `password_hash` | String(255) | Хеш пароля (werkzeug) |
| `first_name` | String(100) | Ім'я |
| `last_name` | String(100) | Прізвище |
| `is_active` | Boolean | Активність акаунта |
| `is_admin` | Boolean | Прапорець адміністратора |
| `created_at` | DateTime (UTC) | Дата створення (TimestampMixin) |
| `updated_at` | DateTime (UTC) | Дата оновлення (TimestampMixin) |
| `last_login_at` | DateTime (UTC) | Останній вхід |

## Course (каталог)

Представляє навчальний продукт в каталозі — без дати. Має багато CourseInstance-ів (проведень).

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInt | PK |
| `title` | String(255) | Назва курсу |
| `slug` | String(200) unique | URL-частина, `/courses/<slug>` |
| `subtitle` | String(500) | Підзаголовок |
| `description` | Text | Повний опис |
| `short_description` | String(500) | Короткий опис для карток |
| `event_type` | String(30) | seminar/webinar/course/masterclass/conference |
| `hero_image`, `card_image` | String(500) | URL зображень |
| `target_audience`, `tags`, `faq` | JSON | Списки |
| `speaker_info`, `agenda` | Text | Текстові блоки |
| `base_price` | Numeric(10,2) | Default-ціна (instance може перевизначити) |
| `cpd_points` | Integer | Default бали БПР |
| `max_participants` | Integer | Default обмеження |
| `trainer_id` | FK trainers | Default-тренер |
| `created_by` | FK users | Хто створив |
| `is_active` | Boolean | Видимий у каталозі |
| `is_featured` | Boolean | Рекомендований |

## CourseInstance (проведення)

Конкретне проведення курсу: коли, де, у якому форматі.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInt | PK |
| `course_id` | FK courses | Батьківський курс |
| `start_date`, `end_date` | DateTime | Дати проведення |
| `event_format` | String(20) | online/offline/hybrid |
| `price`, `cpd_points`, `max_participants` | Overrides | null = взяти з Course |
| `location`, `online_link` | String | Локація |
| `trainer_id` | FK trainers | Override тренера |
| `status` | String(20) | draft/published/active/completed/cancelled |

## CourseRequest (запит на курс)

Клієнтська заявка на проведення курсу, коли немає запланованих дат.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInt | PK |
| `course_id` | FK courses | Курс |
| `user_id` | FK users nullable | Автентифікований користувач (або null для гостя) |
| `email`, `phone`, `message` | Text | Контактні дані |
| `status` | String(20) | pending/responded/scheduled/dismissed |
| `admin_notes` | Text | Нотатки адміна |
| `resolved_by_id`, `resolved_at` | FK + DateTime | Хто і коли обробив |

## Event (LEGACY)

**Застаріла модель** — на шляху видалення. Збережена для сумісності з API, webhooks, legacy URL. Нові курси створюються як Course + CourseInstance.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `title` | String(255) | Назва курсу/заходу |
| `slug` | String(200) | URL-slug, унікальний |
| `subtitle` | String(500) | Підзаголовок hero-секції |
| `description` | Text | Повний опис |
| `short_description` | String(500) | Короткий опис для карток |
| `event_type` | String(30) | Тип: seminar, webinar, course, masterclass, conference |
| `event_format` | String(20) | Формат: online, offline, hybrid |
| `status` | String(20) | Статус: draft, published, active, completed, cancelled |
| `start_date` | DateTime (UTC) | Дата початку |
| `end_date` | DateTime (UTC) | Дата завершення |
| `max_participants` | Integer | Максимум учасників |
| `price` | Numeric(10,2) | Ціна (грн) |
| `location` | String(255) | Місце проведення |
| `online_link` | String(500) | Посилання на онлайн-трансляцію |
| `hero_image` | String(500) | Фонове зображення hero-секції |
| `card_image` | String(500) | Зображення для картки у списку |
| `cpd_points` | Integer | Бали БПР |
| `target_audience` | JSON | Масив текстових блоків "Для кого" |
| `tags` | JSON | Масив тегів курсу |
| `speaker_info` | Text | Додаткова інформація про спікера |
| `agenda` | Text | Програма (текст) |
| `is_featured` | Boolean | Виділений захід |
| `is_active` | Boolean | Активний |
| `created_by` | FK -> users.id | Автор запису |
| `trainer_id` | FK -> trainers.id | Тренер курсу |

## Trainer

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `full_name` | String(200) | ПІБ тренера |
| `slug` | String(200) | URL-slug, унікальний |
| `role` | String(300) | Посада / спеціалізація |
| `bio` | Text | Розгорнутий опис |
| `photo` | String(500) | Шлях до фото |
| `experience_years` | Integer | Стаж (років) |
| `is_active` | Boolean | Активний |
| `created_at` | DateTime (UTC) | TimestampMixin |
| `updated_at` | DateTime (UTC) | TimestampMixin |

## ProgramBlock

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `event_id` | FK -> events.id | Захід |
| `heading` | String(200) | Заголовок блоку ("Теоретична частина", ...) |
| `items` | JSON | Масив пунктів програми |
| `sort_order` | Integer | Порядок відображення |

## EventRegistration

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `user_id` | FK -> users.id (CASCADE) | Користувач |
| `event_id` | FK -> events.id (CASCADE) | Захід |
| `phone` | String(20) | Телефон |
| `specialty` | String(200) | Спеціальність |
| `workplace` | String(300) | Місце роботи |
| `experience_years` | Integer | Стаж (років) |
| `license_number` | String(50) | Номер ліцензії |
| `status` | String(20) | Статус: pending, confirmed, cancelled, completed |
| `payment_status` | String(20) | Статус оплати: unpaid, pending, paid, refunded |
| `payment_amount` | Numeric(10,2) | Сума оплати |
| `payment_id` | String(255) | ID платежу (LiqPay) |
| `paid_at` | DateTime (UTC) | Дата оплати |
| `attended` | Boolean | Чи відвідав захід |
| `cpd_points_awarded` | Integer | Нараховані бали БПР |
| `admin_notes` | Text | Нотатки адміністратора |
| `created_at` | DateTime (UTC) | TimestampMixin |
| `updated_at` | DateTime (UTC) | TimestampMixin |

## Clinic

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `name` | String(300) | Назва клініки |
| `slug` | String(200) | URL-slug, унікальний |
| `short_description` | String(500) | Короткий опис |
| `description` | Text | Повний опис |
| `photo` | String(500) | Фото клініки |
| `sort_order` | Integer | Порядок сортування |
| `is_active` | Boolean | Активна |
| `created_at` | DateTime (UTC) | TimestampMixin |
| `updated_at` | DateTime (UTC) | TimestampMixin |

## EmailLog

Журнал відправлених email-повідомлень. Зберігає аудит-трейл кожного листа із статусом доставки.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `to_email` | String(255) | Адреса одержувача, індексоване |
| `subject` | String(500) | Тема листа |
| `template_name` | String(100) | Назва шаблону листа |
| `status` | String(20) | Статус: pending, sent, failed (індексоване) |
| `error_message` | Text | Повідомлення про помилку (якщо failed) |
| `sent_at` | DateTime (UTC) | Час фактичного відправлення |
| `trigger` | String(50) | Тригер: registration, payment, reminder, status_change, test (індексоване) |
| `registration_id` | FK -> event_registrations.id (SET NULL) | Пов'язана реєстрація |
| `created_at` | DateTime (UTC) | Дата створення (TimestampMixin, індексоване) |
| `updated_at` | DateTime (UTC) | Дата оновлення (TimestampMixin) |

## EmailSettings

Singleton-модель для зберігання SMTP-налаштувань у БД. Керується через адмін-панель. Пароль шифрується Fernet (ключ виводиться з SECRET_KEY).

| Поле | Тип | Опис |
|------|-----|------|
| `id` | Integer | Первинний ключ (завжди 1 -- singleton) |
| `smtp_server` | String(255) | SMTP-сервер |
| `smtp_port` | Integer | Порт SMTP (>0) |
| `smtp_use_ssl` | Boolean | Використовувати SSL |
| `smtp_use_tls` | Boolean | Використовувати TLS |
| `smtp_username` | String(255) | Логін SMTP |
| `smtp_password` | String(500) | Пароль SMTP (зашифрований Fernet) |
| `default_sender` | String(255) | Email відправника за замовчуванням |
| `sender_name` | String(255) | Ім'я відправника |
| `is_enabled` | Boolean | Увімкнено відправку листів |
| `reminder_days` | String(50) | Дні нагадувань через кому (напр. "7,3,1") |
| `created_at` | DateTime (UTC) | TimestampMixin |
| `updated_at` | DateTime (UTC) | TimestampMixin |

**Методи:**
- `get()` -- класовий метод, повертає або створює єдиний рядок (id=1)
- `smtp_password` -- property з шифруванням/розшифруванням через Fernet
- `apply_to_app(app)` -- застосовує налаштування до конфігурації Flask-Mail
- `reminder_days_list` -- property, парсить рядок у список чисел

## PaymentTransaction

Журнал платіжних транзакцій LiqPay. Зберігає деталі кожної спроби оплати.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `registration_id` | FK -> event_registrations.id (CASCADE) | Реєстрація |
| `payment_id` | String(255) | ID транзакції LiqPay |
| `status` | String(50) | Статус: pending, success, failure, reversed |
| `amount` | Numeric(10,2) | Сума транзакції |
| `currency` | String(10) | Валюта (UAH) |
| `transaction_data` | Text | JSON-дані відповіді LiqPay |
| `created_at` | DateTime (UTC) | TimestampMixin |
| `updated_at` | DateTime (UTC) | TimestampMixin |

## SiteSettings

Singleton-модель глобальних налаштувань сайту. Керується через адмін-панель "Налаштування".

| Поле | Тип | Опис |
|------|-----|------|
| `id` | Integer | Первинний ключ (завжди 1 -- singleton) |
| `company_name` | String(100) | Коротка назва (ІПРМ) |
| `company_full_name` | String(500) | Повна назва |
| `company_legal_name` | String(500) | Юридична назва |
| `edrpou` | String(20) | Код ЄДРПОУ |
| `phone_primary` | String(50) | Основний телефон |
| `phone_secondary` | String(50) | Додатковий телефон |
| `email` | String(255) | Email |
| `address` | Text | Адреса |
| `city` | String(200) | Місто |
| `facebook_url` | String(500) | Facebook URL |
| `instagram_url` | String(500) | Instagram URL |
| `telegram_url` | String(500) | Telegram URL |
| `business_hours` | String(200) | Графік роботи |
| `website_url` | String(500) | URL вебсайту |
| `show_labs` | Boolean | Показувати розділ "Лабораторії" у навігації |
| `show_clinics` | Boolean | Показувати розділ "Клініки" у навігації |

**Методи:**
- `get()` -- класовий метод, повертає або створює єдиний рядок (id=1)

## ErrorLog

Журнал помилок додатку. Автоматично записує помилки з rate limiting та фільтрацією сканерів.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `error_code` | Integer | HTTP-код помилки (індексоване) |
| `error_type` | String(100) | Тип виключення (індексоване) |
| `error_message` | Text | Текст помилки |
| `url` | String(500) | URL запиту |
| `method` | String(10) | HTTP-метод |
| `ip_address` | String(45) | IP-адреса клієнта |
| `user_agent` | Text | User-Agent |
| `referrer` | String(500) | Referrer |
| `user_id` | FK -> users.id (SET NULL) | Користувач (якщо авторизований) |
| `traceback` | Text | Повний traceback |
| `request_data` | Text | Дані запиту (JSON, sanitized) |
| `headers` | Text | Заголовки (JSON, sanitized) |
| `resolved` | Boolean | Вирішено (індексоване) |
| `resolved_at` | DateTime (UTC) | Дата вирішення |
| `resolved_by_id` | FK -> users.id (SET NULL) | Хто вирішив |
| `resolution_notes` | Text | Коментар до вирішення |
| `created_at` | DateTime (UTC) | Дата створення (індексоване) |

**Методи:**
- `log_error()` -- класовий метод, записує помилку з sanitization даних
- `get_statistics(days)` -- статистика за N днів
- `get_request_data()` / `get_headers()` -- парсинг JSON-даних

## Зв'язки

```
User 1--* Event              (created_by)
User 1--* EventRegistration  (user_id, CASCADE)
User 1--* ErrorLog           (user_id, SET NULL)
Trainer 1--* Event           (trainer_id)
Event 1--* ProgramBlock      (event_id, CASCADE delete-orphan)
Event 1--* EventRegistration (event_id, CASCADE)
EventRegistration 1--* EmailLog (registration_id, SET NULL)
EventRegistration 1--* PaymentTransaction (registration_id, CASCADE)
```

## Constraints

- `uq_user_event_registration` - один користувач = одна реєстрація на захід
- `ck_events_event_type` - валідація типу заходу
- `ck_events_event_format` - валідація формату
- `ck_events_status` - валідація статусу
- `ck_events_price_non_negative` - ціна >= 0
- `ck_registrations_status` - валідація статусу реєстрації
- `ck_registrations_payment_status` - валідація статусу оплати
- `ck_registrations_experience_non_negative` - стаж >= 0
- `ck_trainers_experience_non_negative` - стаж >= 0
- `ck_email_logs_status` - валідація статусу листа (pending, sent, failed)
- `ck_email_logs_trigger` - валідація тригера (registration, payment, reminder, status_change, test)
- `ck_email_settings_port` - порт > 0
