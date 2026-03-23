# Архітектура

## Структура проекту

```
site-iprm/
├── app/
│   ├── __init__.py              # Application Factory (create_app)
│   ├── extensions.py            # Ініціалізація розширень Flask
│   ├── auth/                    # Blueprint: авторизація
│   │   ├── routes.py            # Login, register, logout, account
│   │   └── forms.py             # LoginForm, RegistrationForm
│   ├── admin/                   # Blueprint: адмін-панель
│   │   ├── routes.py            # Dashboard, CRUD заходів
│   │   ├── forms.py             # EventForm
│   │   └── decorators.py        # admin_required
│   ├── main/                    # Blueprint: головна сторінка
│   │   └── routes.py            # /, /design-system
│   ├── courses/                 # Blueprint: курси
│   │   └── routes.py            # /courses, /course-detail, ...
│   ├── errors/                  # Blueprint: обробка помилок
│   │   └── handlers.py          # 401, 403, 404, 500
│   ├── models/
│   │   ├── mixins.py            # TimestampMixin (created_at, updated_at)
│   │   ├── user.py              # Модель User
│   │   ├── event.py             # Модель Event (курси/заходи)
│   │   ├── trainer.py           # Модель Trainer (тренери)
│   │   └── program_block.py     # Модель ProgramBlock (блоки програми)
│   ├── static/
│   │   ├── css/                 # Стилі (common, auth, admin, page-*, ...)
│   │   ├── js/                  # molecular-background.js
│   │   └── svg/                 # Логотипи та іконки
│   └── templates/
│       ├── base.html            # Базовий шаблон
│       ├── admin/               # Адмін-панель (dashboard, event_edit)
│       ├── auth/                # Сторінки авторизації
│       ├── main/                # Головна сторінка
│       ├── courses/             # Сторінки курсів
│       ├── design_system/       # Дизайн-система
│       ├── errors/              # Сторінки помилок (401, 403, 404, 500)
│       └── partials/            # Header, footer
├── docs/                        # Документація
├── config.py                    # Конфігурація (Dev, Prod, Testing)
├── run.py                       # Точка входу
├── requirements.txt             # Python-залежності
├── .github/workflows/
│   └── deploy.yml               # CI/CD pipeline
└── .env                         # Змінні оточення (не в git)
```

## Архітектурні принципи

- **Application Factory** pattern
- **Blueprint** архітектура для модульної маршрутизації
- **TimestampMixin** - спільний міксін для created_at/updated_at
- **CSS-JS Decoupling** - зовнішні стилі та скрипти, без inline-коду
- **CSRF** захист на всіх формах
- **Rate limiting** - обмеження запитів (200/год за замовчуванням)
- **Security headers** - X-Content-Type-Options, X-Frame-Options, Referrer-Policy
- **Separation of Concerns** - розділення шарів відповідальності

## Blueprints

| Blueprint | Префікс | Опис |
|-----------|---------|------|
| `main` | `/` | Головна сторінка, дизайн-система |
| `auth` | `/auth` | Авторизація, реєстрація, обліковий запис |
| `admin` | `/admin` | Адмін-панель, CRUD заходів |
| `courses` | `/` | Каталог курсів та сторінки окремих курсів |
| `errors` | - | Обробники помилок 401, 403, 404, 500 |
