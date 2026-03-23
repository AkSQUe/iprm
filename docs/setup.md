# Встановлення та запуск

## Вимоги

- Python 3.10+

## Локальний запуск

```bash
# Клонування репозиторію
git clone <repo-url>
cd site-iprm

# Створення віртуального оточення
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Встановлення залежностей
pip install -r requirements.txt

# Налаштування змінних оточення
cp .env.example .env
# Відредагуйте .env та вкажіть SECRET_KEY та DATABASE_URL

# Застосувати міграції
flask db upgrade

# Запуск
python run.py
```

Сервер стартує на `http://localhost:5001`.

## Змінні оточення

| Змінна | Опис | За замовчуванням |
|--------|------|------------------|
| `SECRET_KEY` | Секретний ключ Flask | `dev-secret-key-change-in-production` |
| `DATABASE_URL` | URI бази даних | `sqlite:///iprm.db` |
| `FLASK_CONFIG` | Профіль конфігурації | `default` (development) |

## Міграції бази даних

Проект використовує Flask-Migrate (Alembic) для управління схемою БД.

```bash
# Створити нову міграцію
flask db migrate -m "опис змін"

# Застосувати міграції
flask db upgrade

# Відкотити останню міграцію
flask db downgrade
```

## Залежності

| Пакет | Версія | Призначення |
|-------|--------|-------------|
| Flask | >=3.0 | Веб-фреймворк |
| Flask-SQLAlchemy | >=3.1 | ORM |
| Flask-Login | >=0.6 | Сесії користувачів |
| Flask-WTF | >=1.2 | Форми та CSRF |
| Flask-Migrate | >=4.0 | Alembic-міграції |
| Flask-Limiter | >=3.5 | Rate limiting |
| email-validator | >=2.0 | Валідація email |
| pg8000 | >=1.31 | PostgreSQL-драйвер |
| python-dotenv | >=1.0 | Завантаження .env |
| gunicorn | >=22.0 | WSGI-сервер (prod) |
