# Архітектура

## Структура проекту

Дерево нижче -- карта, а не опис: показані каталоги і ті файли, що задають
структуру. Точні списки моделей і маршрутів живуть у `docs/models.md` і
`docs/routes.md`, і дублювати їх тут означало б завести другу версію правди.

```
site-iprm/
├── app/
│   ├── __init__.py              # Application Factory (create_app), реєстрація
│   │                            # 15 blueprints, context processors, headers
│   ├── extensions.py            # Ініціалізація розширень Flask
│   ├── cli.py                   # CLI-команди (seed, обслуговування, legal docx)
│   ├── utils.py                 # Спільні утиліти (slugify, форматування)
│   ├── undo.py                  # Відкат м'якого видалення (SoftDeleteMixin)
│   ├── i18n.py                  # LocalizedBlueprint, вибір мови, префікси URL
│   ├── i18n_plurals.py          # Множинні форми uk/ru/en
│   ├── icons.py                 # Реєстр іконок для шаблонів
│   ├── js_strings.py            # Рядки, які віддаються в JS (pybabel-екстракція)
│   ├── forms_medical.py         # Спільні поля медичного профілю
│   │
│   ├── main/                    # Blueprint: головна, юридичні сторінки, БПР
│   ├── courses/                 # Blueprint: каталог курсів і заходів
│   ├── online/                  # Blueprint: онлайн-курси Sintegrum, чекаут
│   ├── blog/                    # Blueprint: блог і коментарі
│   ├── media/                   # Blueprint: віддача медіафайлів з реєстру
│   ├── auth/                    # Blueprint: вхід, реєстрація, кабінет
│   ├── admin/                   # Blueprint: адмін-панель
│   │   ├── routes.py            # Агрегатор + дашборд
│   │   ├── routes_*.py          # 50 модулів, по одному на розділ адмінки
│   │   ├── _listing.py          # Спільний серверний список: сорт, фільтри, сторінки
│   │   ├── _helpers.py          # Спільні хелпери адмінських в'ю
│   │   ├── fields.py            # Кастомні поля WTForms
│   │   └── forms.py             # Форми адмінки
│   ├── registration/            # Blueprint: реєстрація на заходи
│   ├── quiz/                    # Blueprint: тестування учасників, сертифікат
│   ├── trainers/                # Blueprint: тренери
│   ├── clinics/                 # Blueprint: клініки
│   ├── payments/                # Blueprint: LiqPay callback, результати оплати
│   ├── api/
│   │   ├── v1/                  # Blueprint: партнерський REST API (HMAC)
│   │   ├── mm_status.py         # Blueprint: статус-обмін з MM Medic
│   │   └── meta_leads.py        # Blueprint: вебхук Meta Lead Ads
│   │
│   ├── rbac/                    # Ролі й права: реєстр, декоратори, CLI-синк
│   │   ├── registry.py          # Оголошення прав (єдине джерело)
│   │   ├── roles.py             # Ролі та їхні набори прав
│   │   ├── decorators.py        # @requires, admin_required
│   │   ├── service.py           # Перевірка прав, синхронізація з БД
│   │   └── cli.py               # flask rbac sync
│   │
│   ├── models/                  # 47 ORM-моделей, по файлу на модель
│   │   ├── __init__.py          # Імпорт усіх моделей (для Alembic autogenerate)
│   │   └── mixins.py            # TimestampMixin, SoftDeleteMixin, BigIntPK
│   ├── data/                    # Довідники-константи (не таблиці)
│   │   ├── specialties.py       # Спеціальності для сертифіката (наказ МОЗ 650)
│   │   └── specializations.py   # Спеціалізації для реєстраційної форми
│   ├── services/                # Шар бізнес-логіки, 71 модуль
│   │   ├── error_handler.py     # Обробники 400/401/403/404/405/429/500/503
│   │   ├── liqpay.py            # LiqPayService (створення платежів, callbacks)
│   │   ├── payment_ops.py       # Операції зі статусами оплат (row-level locking)
│   │   ├── email_service.py     # SMTP-відправка, threading, аудит-лог
│   │   ├── scheduler_service.py # APScheduler (нагадування, persistent jobs)
│   │   ├── backup_service.py    # Резервні копії БД, тривоги, щотижневий звіт
│   │   └── ...                  # Решта -- по домену (quiz, referral, meta, xlsx)
│   │
│   ├── translations/            # Каталоги Flask-Babel (uk -- код, ru, en -- .po)
│   ├── static/
│   │   ├── css/                 # Дизайн-система + page-* (див. CLAUDE.md)
│   │   ├── js/                  # Зовнішні скрипти, без inline
│   │   ├── fonts/               # WOFF2
│   │   ├── svg/                 # Логотипи та іконки
│   │   ├── images/              # Контентні зображення (курси, блог, тренери)
│   │   ├── img/                 # Зображення для зовнішніх споживачів:
│   │   │                        # og:image і логотип у листах -- на них
│   │   │                        # посилаються абсолютним URL
│   │   ├── video/               # Hero-відео
│   │   ├── bpr-documents/       # PDF акредитації БПР (віддаються публічно)
│   │   └── vendor/              # Сторонні бібліотеки (fullcalendar)
│   └── templates/
│       ├── base.html            # Базовий шаблон
│       ├── partials/            # Header, footer, flash, cookie-банер
│       ├── emails/              # Шаблони листів (ім'я = template_name)
│       ├── errors/              # Сторінки помилок
│       ├── certificates/        # Верстка сертифіката (PDF через WeasyPrint)
│       ├── invoices/            # Верстка рахунка
│       ├── design_system/       # Каталог дизайн-системи (/admin/design-system)
│       └── <blueprint>/         # По каталогу на blueprint
│
├── tests/                       # pytest: test_routes, test_services, test_models,
│                                # test_db, test_rbac, test_i18n, test_seo,
│                                # test_cli, test_design_system
├── docs/                        # Документація (на прод не їде, див. deploy.yml)
├── migrations/                  # Alembic-міграції
├── deploy/                      # Серверні конфіги: nginx, systemd, watchdog
├── tools/                       # Інструменти аналізу (ds/, perf/)
├── scripts/                     # Разові й службові скрипти
├── .preview/                    # Прогін прев'ю та знімки (playwright)
├── config.py                    # Конфігурація (Dev, Prod, Testing)
├── run.py                       # Точка входу (development)
├── wsgi.py                      # WSGI entry point (production)
├── requirements.txt             # Python-залежності (діапазони)
├── requirements.lock            # Pinned залежності (production)
├── requirements-dev.txt         # Залежності тестів (CI, локально)
├── babel.cfg                    # Конфіг екстракції рядків pybabel
├── .github/workflows/
│   ├── deploy.yml               # CI/CD: тести -> rsync -> міграції -> рестарт
│   └── verify-lock.yml          # Звірка requirements.txt і requirements.lock
└── .env.example                 # Приклад змінних оточення
```

## Архітектурні принципи

- **Application Factory** pattern
- **Blueprint** архітектура для модульної маршрутизації
- **Service Layer** для бізнес-логіки (app/services/)
- **TimestampMixin** - спільний міксін для created_at/updated_at
- **SoftDeleteMixin + undo** - деструктивна дія, яку можна відкотити повністю
  (відгук, коментар, непривʼязане медіа), не питає підтвердження: виконується
  одразу і показує тост «Повернути» (`app/undo.py`, `undo-toast.js`). Рядок
  лишається з `deleted_at`, запити відсікають його явно (`Model.alive()`),
  а через 30 днів прибирає `purge_soft_deleted`. Діалог підтвердження лишаємо
  там, де відкат був би неповним або дія незворотна
- **CSS-JS Decoupling** - зовнішні стилі та скрипти, без inline-коду
- **CSRF** захист на всіх формах (крім payments webhook)
- **Rate limiting** - обмеження запитів (200/год за замовчуванням)
- **Security headers** - X-Content-Type-Options, X-Frame-Options, Referrer-Policy
- **Separation of Concerns** - розділення шарів відповідальності
- **Structured logging** - глобальна конфігурація логування

## Blueprints

П'ятнадцять зареєстрованих blueprints. `LocalizedBlueprint` (`app/i18n.py`) --
обгортка, що додає мовний префікс (`/ru/...`, `/en/...`); решта працює без
префікса, бо це або API, або службові маршрути.

| Blueprint | Префікс | Мовний префікс | Опис |
|-----------|---------|----------------|------|
| `main` | `/` | так | Головна, юридичні сторінки, документи БПР |
| `courses` | `/courses` | так | Каталог курсів, сторінки заходів, legacy redirects |
| `online` | `/online-courses` | так | Каталог онлайн-курсів Sintegrum, чекаут, видача доступу |
| `blog` | `/blog` | так | Статті та коментарі |
| `auth` | `/auth` | так | Авторизація, реєстрація, кабінет |
| `registration` | `/registration` | так | Реєстрація на заходи, підтвердження, перенесення |
| `quiz` | `/quiz` | так | Тестування учасників, видача сертифіката |
| `trainers` | `/trainers` | так | Список тренерів, сторінки тренерів |
| `clinics` | `/clinics` | так | Список клінік, сторінки клінік |
| `media` | `/` | ні | Віддача файлів з медіареєстру (`MediaFile`) |
| `admin` | `/admin` | ні | Адмін-панель: 50 розділів, права через `app/rbac` |
| `payments` | `/payments` | ні | LiqPay callback, результати оплати (CSRF-exempt) |
| `api_v1` | `/api/v1` | ні | Партнерський REST API (HMAC-підпис) |
| `mm_status` | `/api/partner/mm-medic` | ні | Статус-обмін з MM Medic (CSRF-exempt) |
| `meta_leads` | `/api/webhooks/meta` | ні | Вебхук Meta Lead Ads (CSRF-exempt) |

Обробники помилок -- НЕ blueprint. Вони живуть у
`app/services/error_handler.py` і реєструються через `init_error_handlers(app)`,
бо крім рендеру сторінки ще й пишуть журнал помилок і відсіюють автосканери.

## Інтеграція Sintegrum (онлайн-курси)

Sintegrum -- зовнішня LMS, де фізично відбувається навчання. ІПРМ дзеркалить
її каталог треків, продає доступ і видає учаснику тимчасове посилання.

Потік даних:

```
Sintegrum API                ІПРМ                         MM Medic
GET /external/{company}/
    course            -->  online_course_sync
                           (джоба, щогодини)
                                |
                                v
                           online_courses  --> публічний каталог /online-courses
                           (дзеркало)          адмінка /admin/online-courses
                                |                        |
                                |                        v
                                |              GET /api/v1/online-courses --> дзеркало MM Medic
                                v
                           online_enrollments --> LiqPay (ONL-<id>) --> доступ
```

Чотири рішення, які пояснюють цю схему:

**Дзеркало, а не запити на рендері.** Сторінки читають нашу таблицю, тож
недоступність Sintegrum не робить розділ порожнім, а на курс можуть
посилатися замовлення. Той самий підхід уже виправдав себе в MM Medic
(`app/models/iprm_catalog.py` -- дзеркало каталогу ІПРМ).

**Віддалені й локальні поля розділені.** Синхронізація пише лише `remote_*`;
наші тексти, ціна, посилання й публікація переживають будь-який прогін.

**Тимчасове посилання -- наше.** Ціль редіректу (посилання реєстрації на трек,
згенероване в кабінеті Sintegrum) спільна для всіх покупців і безстрокова,
тому назовні не віддається. Учасник отримує `/online-courses/access/<token>` з
TTL, а редірект робимо ми. Провайдер винесено за інтерфейс
(`app/services/sintegrum_access.py`): якщо Sintegrum колись дасть персональні
посилання через API, зміниться одна реалізація.

Межа цього захисту названа чесно: токен контролює перший перехід, після
редіректу адреса Sintegrum видна в браузері. Це захист від випадкового
поширення (пересланий лист), а не від свідомого.

**Видача доступу не звертається до API Sintegrum.** Учень реєструється сам за
посиланням, тож сценарій «оплата пройшла, доступ не видався через мережу»
неможливий за побудовою. Закріплено тестом, який падає, якщо в цей шлях колись
додадуть мережевий виклик.

Порядок при оплаті обов'язковий: спершу комітиться платіж, потім окремою
транзакцією видається доступ. Зворотний порядок означав би, що збій видачі
відкочує оплату -- гроші прийшли б, а система вважала б, що ні.

Ключ API зберігається в `SiteSettings` зашифрованим Fernet (як
`partner_api_key`, `liqpay_private_key`) і назад не показується -- лише маска
й дата встановлення.
