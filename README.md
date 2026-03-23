# IPRM - Інститут Плазмотерапії та Регенеративної Медицини

Веб-сайт Інституту Плазмотерапії та Регенеративної Медицини. Інформаційний портал з каталогом курсів, системою авторизації та обліковими записами користувачів.

## Технології

- **Backend:** Flask 3.0+, SQLAlchemy ORM, Flask-Login, Flask-WTF, Flask-Migrate, Flask-Limiter
- **Frontend:** Jinja2, CSS + Tailwind CSS (гібридна архітектура), Canvas API
- **База даних:** SQLite (dev), PostgreSQL (prod, через pg8000), Alembic-міграції
- **Деплой:** GitHub Actions, rsync на VPS, systemd + gunicorn
- **Безпека:** CSRF, rate limiting, security headers, admin-декоратор
- **Мова інтерфейсу:** Українська

## Документація

| Розділ | Опис |
|--------|------|
| [Архітектура](docs/architecture.md) | Структура проекту, принципи, blueprints |
| [Маршрути](docs/routes.md) | Таблиця всіх URL-ендпоінтів |
| [Модель даних](docs/models.md) | Таблиці БД: User, Event, Trainer, ProgramBlock, зв'язки |
| [Встановлення](docs/setup.md) | Локальний запуск, змінні оточення, міграції, залежності |
| [Деплой](docs/deployment.md) | VPS, SSH, CI/CD, секрети GitHub |
