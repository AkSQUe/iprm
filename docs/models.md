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
| `proof_stats` | JSON | Смуга цифр довіри: `[{value, label}]` |
| `benefits` | JSON | Картки «що зміниться у практиці»: `[{title, text}]` |
| `practice_note_title`, `practice_note_text` | String(200), Text | Акцентна плашка в блоці програми |
| `gallery_intro` | String(500) | Лід над галереєю |

Галерея власного поля не має: фото беруться з медіа-реєстру
(`entity_type='course'`, `usage_type='gallery'`) через властивість
`Course.gallery`. Порядок — `MediaFile.sort_order`, підпис — `MediaFile.caption`.

Контентні поля продажної сторінки порожні за замовчуванням: курс, якому їх не
заповнили, просто не показує відповідну секцію.

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

### Місткість: місце тримає лише оплачена реєстрація

Правило від 12.08.2026, єдина реалізація -- `app/services/seating.py`.
Зайнятим вважається місце з `payment_status='paid'` і не-скасованим
статусом; неоплачений `pending` продаж більше не блокує. Звідси рахують
місця всі: публічні лістинги (`course_listing`), гейт реєстрації
(`registration_service.check_capacity`), адмінка, партнерське API,
xlsx-звіти.

Наслідок -- **перевищення пулу**: оплата може прийти після того, як місця
розібрали. Гроші не відхиляються, натомість подія стає видимою -- у
розкладі адмінки колонка «Місця» червоніє (`7/6`), а адміністраторам
(адресати правила `payment`) йде лист `overbooking_alert`.

## CourseRequest (запит на курс)

Клієнтська заявка на проведення курсу, коли немає запланованих дат.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInt | PK |
| `course_id` | FK courses | Курс |
| `user_id` | FK users nullable | Автентифікований користувач (або null для гостя) |
| `email`, `phone`, `message` | Text | Контактні дані |
| `name` | String(120) nullable | Ім'я (поле продажної форми) |
| `messenger` | String(20) nullable | telegram/viber/whatsapp/phone/email |
| `consent_at` | DateTime nullable | Коли дано згоду на обробку даних |
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
| `photo_media_id` | FK media_files | Фото (лише через медіа-реєстр) |
| `experience_years` | Integer | Стаж (років) |
| `highlights` | JSON | Короткі цифри для блоку тренера: `[{value, label}]` |
| `is_active` | Boolean | Активний |
| `created_at` | DateTime (UTC) | TimestampMixin |
| `updated_at` | DateTime (UTC) | TimestampMixin |

## ProgramBlock

Належить АБО офлайн-курсу, АБО онлайн-курсу — рівно одному з двох. Поліморфність
свідома: блок програми виглядає й редагується однаково для обох типів, тож
окрема сутність (чи JSON-колонка на `online_courses`) дала б два джерела правди
і два редактори в адмінці.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `course_id` | FK -> courses.id nullable | Офлайн-курс |
| `online_course_id` | FK -> online_courses.id nullable | Онлайн-курс |
| `heading` | String(200) | Заголовок блоку ("Теоретична частина", ...) |
| `items` | JSON | Масив пунктів програми |
| `sort_order` | Integer | Порядок відображення |

`CheckConstraint ck_program_blocks_single_owner`:
`(course_id IS NULL) <> (online_course_id IS NULL)`. Блок без власника мовчки
випав би з обох сторінок і лишився б у базі назавжди, тому вставка такого рядка
падає одразу. Властивість `ProgramBlock.owner` віддає курс незалежно від типу.

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
| `promo_code_id` | FK -> promo_codes.id (SET NULL) | Застосований промокод |
| `discount_amount` | Numeric(10,2) | Знімок знижки (payment_amount уже без неї) |
| `attended` | Boolean | Чи відвідав захід |
| `cpd_points_awarded` | Integer | Нараховані бали БПР |
| `admin_notes` | Text | Нотатки адміністратора |
| `created_at` | DateTime (UTC) | TimestampMixin |
| `updated_at` | DateTime (UTC) | TimestampMixin |

Зв'язок: `certificate` -> Certificate (one-to-one, cascade delete-orphan).

## PromoCode / PromoRedemption

Промокоди зі знижкою на реєстрацію -- повний опис у
[docs/promo-codes.md](promo-codes.md).

**`promo_codes`**

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `code` | String(64) | Код як його ввів адмін (для показу) |
| `code_norm` | String(64), UNIQUE | casefold без пробілів -- ключ пошуку |
| `description` | String(255) | Для кого/навіщо виданий |
| `discount_type` | String(10) | `percent` або `amount` |
| `discount_value` | Numeric(10,2) | Відсоток (<=100) або сума в грн |
| `max_uses` | Integer | Загальний ліміт; NULL -- без обмежень |
| `per_user_limit` | Integer | Ліміт на одну людину; NULL -- без обмежень |
| `used_count` | Integer | Денормалізований лічильник активних списань |
| `valid_from` / `valid_until` | DateTime (UTC) | Вікно дії; NULL -- безстроково |
| `course_id` | FK -> courses.id (CASCADE) | Звузити до курсу |
| `instance_id` | FK -> course_instances.id (CASCADE) | Звузити до проведення |
| `is_active` | Boolean | Вимкнений код не спрацює |
| `created_by_id` | FK -> users.id (SET NULL) | Хто створив |

**`promo_redemptions`** -- реєстр застосувань (джерело правди для лічильника)

Реєстр СПІЛЬНИЙ для обох типів замовлень: заповнене рівно одне з полів
`registration_id` / `enrollment_id` (CHECK `ck_promo_redemptions_single_owner`).
Розводити їх по таблицях означало б, що код із `max_uses=1` можна
використати двічі -- по разу на захід і на онлайн-курс, і ліміт «на одну
людину» рахувався б окремо в кожному.

Промокод, прив'язаний до `course_id` чи `instance_id`, на онлайн-курси НЕ
діє: у них немає відповідника цим полям (`promo_service.validate_for_online`).

| Поле | Тип | Опис |
|------|-----|------|
| `promo_code_id` | FK -> promo_codes.id (CASCADE) | Код |
| `registration_id` | FK -> event_registrations.id (CASCADE), NULLABLE | Реєстрація на захід |
| `enrollment_id` | FK -> online_enrollments.id (CASCADE), NULLABLE | Купівля онлайн-курсу |
| `user_id` | FK -> users.id (CASCADE) | Учасник (для ліміту на людину) |
| `original_amount` / `discount_amount` / `final_amount` | Numeric(10,2) | Сума до, знижка, сума після |
| `status` | String(10) | `applied` або `voided` |
| `voided_at` / `notes` | DateTime / String(255) | Коли і чому анульовано |

Partial-unique index `uq_promo_redemptions_active_reg` (`registration_id`
WHERE `status = 'applied'`) гарантує рівно одне активне списання на
реєстрацію; анульовані рядки лишаються в історії.

## Certificate

Сертифікат учасника. Видається адміністратором вручну для реєстрації; видача
відкриває доступ у кабінеті та надсилає лист з PDF. Поля-знімки незмінні після
видачі (правки курсу/користувача не змінюють виданий сертифікат). PDF
генерується WeasyPrint (HTML -> PDF), зберігається у `CERTIFICATE_FOLDER`.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `registration_id` | FK -> event_registrations.id (CASCADE), unique | Одна реєстрація = один сертифікат |
| `user_id` | FK -> users.id (CASCADE) | Власник (денормалізовано) |
| `number` | String(40) unique | Номер БПР: `РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ` (рік заходу - провайдер - захід - глобальний № учасника), напр. `2026-2738-1028974-000001` |
| `recipient_name` | String(255) | Знімок ПІБ на момент видачі |
| `event_title` | String(500) | Знімок назви заходу |
| `event_date` | DateTime (UTC) | Знімок дати заходу |
| `cpd_points` | Integer | Знімок балів БПР |
| `lecturer_name` | String(200) | Знімок імені лектора (тренер проведення) |
| `issued_at` | DateTime (UTC) | Дата видачі |
| `issued_by_id` | FK -> users.id (SET NULL) | Адмін, що видав |
| `pdf_path` | String(255) | Шлях до PDF (posix) відносно CERTIFICATE_FOLDER |
| `revoked` | Boolean | Відкликано |
| `revoked_at` | DateTime (UTC) | Дата відкликання |
| `created_at`, `updated_at` | DateTime (UTC) | TimestampMixin |

### Нумерація: монотонний лічильник, а не COUNT(*)

Сегмент «номер учасника» видається лічильником
`SiteSettings.bpr_participant_counter` (лекторський -- `bpr_lecturer_counter`,
власний діапазон 1xxxxx) під блокуванням singleton-рядка налаштувань
(`SELECT ... FOR UPDATE`). Реалізація -- `_allocate_number_segment` і
`_next_free_number` у `app/services/certificate_service.py`.

Раніше сегмент брався як `COUNT(*) + 1` по таблиці сертифікатів. Це мало два
режими відмови, і обидва стають досяжними, щойно видача перестає бути ручною:
дві одночасні видачі отримували один номер (retry при цьому не сходився, бо
перераховував ту саму кількість), а після видалення будь-якого сертифіката
лічильник ішов назад і колізія ставала постійною. Пропуски в нумерації
допустимі -- монотонність важливіша за щільність. Лічильники **не правити
вручну**: зменшення дасть колізії з уже виданими номерами.

Повторна видача відкликаного сертифіката **зберігає** номер і `pdf_path`: номер
уже пішов у реєстр БПР і на руки людині, а раніше він мовчки змінювався, і PDF
під старим номером лишався на диску сиротою.

## CourseQuiz / QuizQuestion / QuizAttempt

Тестування учасників після заходу. Повний опис потоку --
[docs/plan-testing.md](plan-testing.md).

**`course_quizzes`** -- налаштування тесту. Прив'язка XOR: або курс (базовий
набір, спільний для всіх проведень), або конкретне проведення
(перевизначення).

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `course_id` | FK -> courses.id (CASCADE), nullable | Тест курсу |
| `instance_id` | FK -> course_instances.id (CASCADE), nullable | Перевизначення для проведення |
| `questions_per_attempt` | Integer, default 10 | Скільки питань тягнемо з банку |
| `passing_score` | Integer, default 8 | Скільки правильних потрібно (кількість, не відсоток) |
| `max_attempts` | Integer, default 3 | Ліміт спроб |
| `shuffle_answers` | Boolean, default True | Перемішувати варіанти |
| `is_active` | Boolean, default **False** | Чернетка, поки банк не готовий |
| `intro` | Text, nullable | Вступний текст перед стартом (перекладний) |
| `deadline_days_after_end` | Integer, nullable | Днів на складання після завершення заходу; NULL -- без обмеження, 0 -- до 23:59 останнього дня |

`__translatable__ = ('intro',)` -- сторінку тесту читають трьома мовами;
редагується мовними вкладками в білдері (префікс `trqz__<id>`).

Дедлайн рахується від `end_date` проведення (з відкатом на `start_date`, якщо
не заповнене), а не абсолютною міткою: тест може належати курсу, спільному для
десятка проведень. Межа доби -- київська (`app.utils.KYIV`), бо правило
сформульоване для людини як «до 23:59».

Обмеження: `ck_course_quizzes_owner` (рівно одне з course_id/instance_id),
`ck_course_quizzes_passing_within` (`passing_score <= questions_per_attempt`),
`ck_course_quizzes_deadline_non_negative`, плюс позитивність налаштувань.
Partial-unique `uq_course_quizzes_course`/`_instance` -- один тест на курс і
один на проведення.

Властивості: `bank_size`, `active_questions`, `is_ready` (банк достатній І всі
питання коректні -- окремо від `is_active`, бо адмін міг увімкнути тест і потім
зіпсувати питання).

**`quiz_questions`** -- банк питань.

| Поле | Тип | Опис |
|------|-----|------|
| `quiz_id` | FK -> course_quizzes.id (CASCADE) | Тест |
| `text` | Text | Питання |
| `answers` | JSON | `[{"text": str, "is_correct": bool}, ...]` -- рівно 4, рівно один правильний |
| `sort_order` | Integer | Порядок у банку |
| `is_active` | Boolean, default True | Вивести з банку, не втрачаючи історії |
| `translations` | JSON | `TranslatableMixin`: `('text', 'answers')` |

Варіанти -- JSON, а не окрема таблиця: прецедент `program_blocks.items` і
`courses.faq`, а механізм перекладів це вже вміє (`walk_leaves` обходить лише
str-листя, тож булеве `is_correct` ігнорується сам собою). Ключ тексту мусить
називатися саме `text` -- ключі з `TECHNICAL_KEYS` (`code`, `type`, `id`) з
перекладу виключені. `answer_texts()` віддає ЛИШЕ тексти: правильність назовні
не йде ніколи.

**`quiz_attempts`** -- спроби.

| Поле | Тип | Опис |
|------|-----|------|
| `registration_id` | FK -> event_registrations.id (CASCADE) | Реєстрація |
| `user_id` | FK -> users.id (CASCADE) | Денормалізовано (як у Certificate) |
| `quiz_id` | FK -> course_quizzes.id (**SET NULL**) | Видалений тест не стирає історію |
| `attempt_number` | Integer | 1, 2, 3...; unique разом з registration_id |
| `question_ids` | JSON | Питання спроби у зафіксованому порядку |
| `answer_order` | JSON | `{"<question_id>": [перемішані індекси]}` |
| `submitted_answers` | JSON | `{"<question_id>": позиція}` -- пишеться інкрементально |
| `score` / `total` / `passing_score` | Integer | Результат і знімки параметрів спроби |
| `passed` | Boolean | Склав |
| `started_at` / `submitted_at` | DateTime (UTC) | `submitted_at IS NULL` -- спроба в процесі |

Набір питань і порядок варіантів фіксуються на старті: інакше кожне
перезавантаження перемішувало б тест, а спроб лише три. Відповіді пишуться
інкрементально, тож закрита вкладка не з'їдає спробу.

Поля в `EventRegistration`: `quiz_passed_at` (денормалізація для лістингів і
гейта) і `quiz_extra_attempts` (додаткові спроби від адміна -- числом, а не
прапорцем, щоб можна було видати рівно одну).

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

## OnlineCourse (онлайн-курс, дзеркало Sintegrum)

Каталог онлайн-навчання, що фізично відбувається в Sintegrum. Це ДЗЕРКАЛО
чужого каталогу плюс наші дані про продаж, тому поля розділені на два набори.

Не плутати з `Course`: той описує офлайн-захід із проведеннями, датами,
містами, тарифами й сертифікатами БПР. Тут нічого цього немає.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `sintegrum_id` | Integer UNIQUE | Ідентифікатор треку в Sintegrum |
| `remote_name` | String(255) | Назва з Sintegrum |
| `remote_description` | Text | Опис з Sintegrum |
| `remote_price` | Numeric(10,2) | Ціна з Sintegrum -- ДОВІДКОВА, у продаж не йде |
| `remote_status` | Integer | 0 неактивний, 1 активний, 2 архів |
| `remote_payload` | JSON | Сирий об'єкт останнього прогону синхронізації |
| `first_seen_at` / `last_seen_at` | DateTime (UTC) | Коли вперше й востаннє бачили у видачі |
| `is_vanished` | Boolean | Зник із видачі Sintegrum (НЕ видаляємо) |
| `slug` | String(200) UNIQUE | Наша адреса сторінки |
| `title` / `description` / `short_description` | | Наші тексти; порожньо -> беремо з Sintegrum |
| `price` | Numeric(10,2) | НАША ціна продажу. Обов'язкова для публікації |
| `currency` | String(3) | Валюта, типово UAH |
| `duration_hours`, `cpd_points` | Integer | Тривалість; бали БПР (довідково) |
| `is_published`, `is_featured`, `sort_order` | | Керування каталогом |
| `hero_media_id`, `card_media_id` | FK -> media_files | Зображення через медіа-реєстр |
| `card_avatar_src` | String(1000) | Посилання Sintegrum, з якого зроблено `card_media` |
| `access_url` | String(1000) | Посилання реєстрації Sintegrum. НІКОЛИ не віддається назовні |
| `access_ttl_hours` | Integer | Термін життя виданого токена; порожньо -> з налаштувань |
| `target_audience`, `faq` | JSON | Аудиторія та поширені запитання |
| `final_cta_text` | String(300) | Фінальний заклик |
| `proof_stats`, `benefits` | JSON | Як у `Course` |
| `practice_note_title`, `practice_note_text` | String(200), Text | Як у `Course` |
| `gallery_intro` | String(500) | Лід над галереєю |
| `trainer_id` | FK -> trainers nullable | Автор курсу (у Sintegrum тренера немає) |

Контентні поля продажної сторінки дзеркалять однойменні поля `Course`: сторінки
онлайн- і офлайн-курсу зібрані з тих самих партіалів, тож і дані називаються
однаково. Програма — через поліморфний `ProgramBlock.online_course_id`,
галерея — через `OnlineCourse.gallery` (`entity_type='online_course'`).

Синхронізація (`app/services/online_course_sync.py`) пише ЛИШЕ `remote_*`.
Локальні поля переживають будь-яку кількість прогонів -- інакше кожен прогін
затирав би редакторську роботу.

Виняток -- обкладинка (`app/services/online_course_media.py`). Фід віддає
недокументоване `avatar_link`, і ми затягуємо файл у власний медіа-реєстр
(WebP + варіант `card`), а не показуємо чужим посиланням: інакше домен
довелося б вносити в `img-src` CSP, а картка ламалася б разом із їхнім
файловим сервером. `card_avatar_src` розрізняє три стани: порожньо без
`card_media_id` -- обкладинки ще немає; заповнено -- картинку затягнули ми
(при зміні посилання оновимо, стару копію приберемо); порожньо ПРИ заповненому
`card_media_id` -- зображення поставила людина, синхронізація його не чіпає.
Обкладинки йдуть другим проходом, після коміту дзеркала й окремою транзакцією
на курс: збита картинка не має ні валити прогін, ні лишати файли-сироти.

`missing_for_publication` повертає СПИСОК причин, чому курс не можна
опублікувати (немає ціни, немає `access_url`, курс зник), а не просто `False`:
адмін має бачити, що саме доробити.

## OnlineEnrollment (купівля онлайн-курсу)

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ; `order_id` = `ONL-<id>` |
| `user_id` | FK -> users.id (CASCADE) | Покупець |
| `online_course_id` | FK -> online_courses.id (RESTRICT) | Курс |
| `status` | String(20) | pending / active / cancelled |
| `payment_status` | String(20) | unpaid / pending / paid / refunded |
| `payment_amount` | Numeric(10,2) | Сума, зафіксована при оформленні |
| `payment_id`, `payment_method`, `paid_at` | | Реквізити платежу |
| `promo_code_id` | FK -> promo_codes.id (SET NULL) | Застосований промокод |
| `discount_amount` | Numeric(10,2) | Знімок знижки (payment_amount уже після неї) |
| `sintegrum_student_id` | Integer | Під майбутню звірку прогресу (зараз порожній) |
| `provisioned_at` | DateTime (UTC) | Коли видано доступ |
| `provision_error` | Text | Остання причина невдалої видачі |
| `access_token` | String(64) UNIQUE | НАШ токен, не адреса Sintegrum |
| `access_expires_at` | DateTime (UTC) | Термін дії токена |
| `access_issued_count` | Integer | Скільки разів видавали (перевипуски) |
| `access_last_opened_at` | DateTime (UTC) | Коли востаннє переходили |

Часткова унікальність `(user_id, online_course_id) WHERE status <> 'cancelled'`
-- одна людина не купує той самий курс двічі, але скасоване замовлення не
блокує повторну спробу.

`payment_status='paid'` при порожньому `provisioned_at` -- аварійний стан
(«заплатив, доступу немає»). Його щодесять хвилин підбирає джоба
`retry_online_access_provisioning`.

## PaymentTransaction

Журнал платіжних транзакцій LiqPay. Зберігає деталі кожної спроби оплати.

Журнал СПІЛЬНИЙ для обох типів замовлень: заповнене рівно одне з полів
`registration_id` / `enrollment_id`, це закріплено CHECK-ом
`ck_payment_transactions_single_owner`. Розділяти журнали не можна --
звірка з виписками LiqPay має читатися одним запитом, інакше половина
операцій завжди лишалася б поза звітом.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `registration_id` | FK -> event_registrations.id (CASCADE), NULLABLE | Реєстрація на захід |
| `enrollment_id` | FK -> online_enrollments.id (CASCADE), NULLABLE | Купівля онлайн-курсу |
| `order_id` | String(100) | `REG-<id>` або `ONL-<id>` |
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
- `ck_program_blocks_single_owner` - блок програми належить рівно одному курсу
  (офлайновому АБО онлайновому), сироти неможливі
- `ck_course_requests_messenger` - валідація каналу зв'язку; NULL дозволено
  (історичні заявки й коротка форма запиту месенджера не мають)
