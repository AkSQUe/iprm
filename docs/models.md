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

## Event

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

## Зв'язки

```
User 1--* Event              (created_by)
User 1--* EventRegistration  (user_id, CASCADE)
Trainer 1--* Event           (trainer_id)
Event 1--* ProgramBlock      (event_id, CASCADE delete-orphan)
Event 1--* EventRegistration (event_id, CASCADE)
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
