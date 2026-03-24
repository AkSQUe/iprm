# Архітектура

## Структура проекту

```
site-iprm/
├── app/
│   ├── __init__.py              # Application Factory (create_app)
│   ├── extensions.py            # Ініціалізація розширень Flask
│   ├── cli.py                   # CLI-команди (seed-courses)
│   ├── utils.py                 # Спільні утиліти (slugify)
│   ├── auth/                    # Blueprint: авторизація
│   │   ├── routes.py            # Login, register, logout, account
│   │   └── forms.py             # LoginForm, RegistrationForm
│   ├── admin/                   # Blueprint: адмін-панель
│   │   ├── routes.py            # Агрегатор маршрутів
│   │   ├── routes_events.py     # CRUD заходів
│   │   ├── routes_trainers.py   # CRUD тренерів
│   │   ├── routes_registrations.py # Управління реєстраціями
│   │   ├── routes_stubs.py      # Dashboard, платежі, stub-секції
│   │   ├── forms.py             # EventForm, TrainerForm
│   │   └── decorators.py        # admin_required
│   ├── main/                    # Blueprint: головна + юридичні сторінки
│   │   └── routes.py            # /, /design-system, /offer, /privacy, ...
│   ├── courses/                 # Blueprint: курси
│   │   └── routes.py            # /courses, /courses/<slug>, legacy redirects
│   ├── trainers/                # Blueprint: тренери
│   │   └── routes.py            # /trainers, /trainers/<slug>
│   ├── clinics/                 # Blueprint: клініки
│   │   └── routes.py            # /clinics, /clinics/<slug>
│   ├── registration/            # Blueprint: реєстрація на заходи
│   │   ├── routes.py            # /registration/<id>/register, confirmation
│   │   └── forms.py             # EventRegistrationForm
│   ├── payments/                # Blueprint: платежі LiqPay
│   │   └── routes.py            # /payments/liqpay/callback, success, failure
│   ├── services/                # Шар бізнес-логіки
│   │   └── liqpay.py            # LiqPayService (створення платежів, callbacks)
│   ├── errors/                  # Blueprint: обробка помилок
│   │   └── handlers.py          # 401, 403, 404, 500
│   ├── models/
│   │   ├── mixins.py            # TimestampMixin, BigIntPK
│   │   ├── user.py              # Модель User
│   │   ├── event.py             # Модель Event (курси/заходи)
│   │   ├── trainer.py           # Модель Trainer (тренери)
│   │   ├── program_block.py     # Модель ProgramBlock (блоки програми)
│   │   ├── registration.py      # Модель EventRegistration
│   │   └── clinic.py            # Модель Clinic (клініки)
│   ├── static/
│   │   ├── css/                 # Стилі (common, auth, admin, page-*, ...)
│   │   ├── js/                  # theme-toggle, molecular-background, admin-event-edit
│   │   ├── fonts/               # Inter WOFF2 (400-700)
│   │   └── svg/                 # Логотипи та іконки
│   └── templates/
│       ├── base.html            # Базовий шаблон
│       ├── admin/               # Адмін-панель
│       ├── auth/                # Сторінки авторизації
│       ├── main/                # Головна, юридичні сторінки
│       ├── courses/             # Сторінки курсів
│       ├── trainers/            # Сторінки тренерів
│       ├── clinics/             # Сторінки клінік
│       ├── registration/        # Реєстрація та підтвердження
│       ├── payments/            # Результат оплати (success, failure)
│       ├── design_system/       # Дизайн-система
│       ├── errors/              # Сторінки помилок (401, 403, 404, 500)
│       └── partials/            # Header, footer, flash_messages, cookie_banner
├── tests/                       # Тести (pytest)
│   ├── test_db/                 # Тести БД (indexes, constraints, queries)
│   └── test_models/             # Тести моделей
├── docs/                        # Документація
├── migrations/                  # Alembic-міграції
├── config.py                    # Конфігурація (Dev, Prod, Testing)
├── run.py                       # Точка входу (development)
├── wsgi.py                      # WSGI entry point (production)
├── requirements.txt             # Python-залежності (діапазони)
├── requirements.lock            # Pinned залежності (production)
├── .github/workflows/
│   └── deploy.yml               # CI/CD pipeline
└── .env.example                 # Приклад змінних оточення
```

## Архітектурні принципи

- **Application Factory** pattern
- **Blueprint** архітектура для модульної маршрутизації
- **Service Layer** для бізнес-логіки (app/services/)
- **TimestampMixin** - спільний міксін для created_at/updated_at
- **CSS-JS Decoupling** - зовнішні стилі та скрипти, без inline-коду
- **CSRF** захист на всіх формах (крім payments webhook)
- **Rate limiting** - обмеження запитів (200/год за замовчуванням)
- **Security headers** - X-Content-Type-Options, X-Frame-Options, Referrer-Policy
- **Separation of Concerns** - розділення шарів відповідальності
- **Structured logging** - глобальна конфігурація логування

## Blueprints

| Blueprint | Префікс | Опис |
|-----------|---------|------|
| `main` | `/` | Головна сторінка, дизайн-система, юридичні сторінки |
| `auth` | `/auth` | Авторизація, реєстрація, обліковий запис |
| `admin` | `/admin` | Адмін-панель, CRUD заходів/тренерів, реєстрації, LiqPay |
| `courses` | `/courses` | Каталог курсів, сторінки заходів, legacy redirects |
| `trainers` | `/trainers` | Список тренерів, сторінки тренерів |
| `clinics` | `/clinics` | Список клінік, сторінки клінік |
| `registration` | `/registration` | Реєстрація на заходи, підтвердження |
| `payments` | `/payments` | LiqPay callback, результати оплати |
| `errors` | - | Обробники помилок 401, 403, 404, 500 |
