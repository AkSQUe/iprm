# IPRM - Інститут Плазмотерапії та Регенеративної Медицини

Веб-сайт Інституту Плазмотерапії та Регенеративної Медицини. Інформаційний портал з каталогом курсів, системою авторизації та обліковими записами користувачів.

## Технології

- **Backend:** Flask 3.0+, SQLAlchemy ORM, Flask-Login, Flask-WTF, Flask-Migrate, Flask-Limiter
- **Frontend:** Jinja2, CSS + Tailwind CSS (гібридна архітектура), Canvas API
- **База даних:** SQLite (dev), PostgreSQL (prod, через pg8000), Alembic-міграції
- **Деплой:** GitHub Actions, rsync на VPS, systemd + gunicorn
- **Безпека:** CSRF, rate limiting, security headers, admin-декоратор
- **Мови інтерфейсу:** Українська (базова), російська та англійська через Flask-Babel (впроваджується, див. [docs/i18n.md](docs/i18n.md))

## Документація

| Розділ | Опис |
|--------|------|
| [Архітектура](docs/architecture.md) | Структура проекту, принципи, blueprints |
| [Маршрути](docs/routes.md) | Таблиця всіх URL-ендпоінтів |
| [Модель даних](docs/models.md) | Таблиці БД: User, Event, Trainer, ProgramBlock, зв'язки |
| [Встановлення](docs/setup.md) | Локальний запуск, змінні оточення, міграції, залежності |
| [Мультимовність](docs/i18n.md) | Flask-Babel: мови uk/ru/en, каталоги перекладів, робочий цикл, фази |
| [Промокоди](docs/promo-codes.md) | Знижки за кодом: типи, ліміти, область дії, B2B-сценарії, адмінка |
| [Деплой](docs/deployment.md) | VPS, SSH, CI/CD, секрети GitHub |
| [План робіт plasma-regen](docs/plan-robit-plasma-regen.md) | Погоджений план правок (переписка 08.07.2026) |
| [Todo виконання плану](docs/todo-plasma-regen.md) | Статуси завдань, журнал комітів, фази складних робіт |
| [Референс Multimed](docs/dopovnennya-multimed.md) | Прототип-референс UI/контенту для карток, фільтрів, B2B |

## Інструменти

| Інструмент | Опис |
|--------|------|
| [Замір швидкості](tools/perf/README.md) | `tools/perf/perf_check.py` - Core Web Vitals, вага ресурсів, бюджети і порівняння з базовою лінією. Історія прогонів - `/admin/perf` (заміри надсилаються з `--push`, на сервері браузер не запускається). Аудит із виправленнями - слеш-команда `/perf-audit` |
| `scripts/ui_screenshots.py` | Обхід сайту з повносторінковими скріншотами у desktop/tablet/mobile + HTML-галерея |
