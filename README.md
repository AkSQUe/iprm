# IPRM - Інститут Плазмотерапії та Регенеративної Медицини

Веб-сайт Інституту Плазмотерапії та Регенеративної Медицини. Інформаційний портал з каталогом курсів, системою авторизації та обліковими записами користувачів.

## Технології

- **Backend:** Flask 3.0+, SQLAlchemy ORM, Flask-Login, Flask-WTF
- **Frontend:** Jinja2, CSS + Tailwind CSS (гібридна архітектура), Canvas API
- **База даних:** SQLite (dev), PostgreSQL (prod, через pg8000)
- **Деплой:** GitHub Actions, rsync на VPS, systemd + gunicorn
- **Мова інтерфейсу:** Українська

## Структура проекту

```
site-iprm/
├── app/
│   ├── __init__.py              # Application Factory (create_app)
│   ├── extensions.py            # Ініціалізація розширень Flask
│   ├── auth/                    # Blueprint: авторизація
│   │   ├── routes.py            # Login, register, logout, account
│   │   └── forms.py             # LoginForm, RegistrationForm
│   ├── main/                    # Blueprint: головна сторінка
│   │   └── routes.py            # /, /design-system
│   ├── courses/                 # Blueprint: курси
│   │   └── routes.py            # /courses, /course-detail, ...
│   ├── errors/                  # Blueprint: обробка помилок
│   │   └── handlers.py          # 404, 500
│   ├── models/
│   │   ├── user.py              # Модель User
│   │   ├── event.py             # Модель Event (курси/заходи)
│   │   ├── trainer.py           # Модель Trainer (тренери)
│   │   └── program_block.py     # Модель ProgramBlock (блоки програми)
│   ├── static/
│   │   ├── css/                 # Стилі (common, auth, page-*, ...)
│   │   ├── js/                  # molecular-background.js
│   │   └── svg/                 # Логотипи та іконки
│   └── templates/
│       ├── base.html            # Базовий шаблон
│       ├── auth/                # Сторінки авторизації
│       ├── main/                # Головна сторінка
│       ├── courses/             # Сторінки курсів
│       ├── design_system/       # Дизайн-система
│       ├── errors/              # Сторінки помилок
│       └── partials/            # Header, footer
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
- **CSS-JS Decoupling** - зовнішні стилі та скрипти, без inline-коду
- **CSRF** захист на всіх формах
- **Separation of Concerns** - розділення шарів відповідальності

## Blueprints

| Blueprint | Префікс | Опис |
|-----------|---------|------|
| `main` | `/` | Головна сторінка, дизайн-система |
| `auth` | `/auth` | Авторизація, реєстрація, обліковий запис |
| `courses` | `/` | Каталог курсів та сторінки окремих курсів |
| `errors` | - | Обробники помилок 404, 500 |

## Маршрути

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/` | Головна сторінка |
| GET | `/design-system` | Дизайн-система |
| GET/POST | `/auth/login` | Вхід |
| GET/POST | `/auth/register` | Реєстрація |
| POST | `/auth/logout` | Вихід |
| GET | `/auth/account` | Обліковий запис |
| GET | `/courses` | Список курсів |
| GET | `/course-detail` | Курс гінекології |
| GET | `/course-stomatology` | Курс косметології |
| GET | `/course-orthopedics` | Курс вікового менеджменту |

## Модель даних

### User

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `email` | String(255) | Унікальний, індексований |
| `password_hash` | String(255) | Хеш пароля (werkzeug) |
| `first_name` | String(100) | Ім'я |
| `last_name` | String(100) | Прізвище |
| `is_active` | Boolean | Активність акаунта |
| `created_at` | DateTime (UTC) | Дата створення |
| `updated_at` | DateTime (UTC) | Дата оновлення |
| `last_login_at` | DateTime (UTC) | Останній вхід |

### Event

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `title` | String(255) | Назва курсу/заходу |
| `slug` | String(200) | URL-slug, унікальний |
| `subtitle` | String(500) | Підзаголовок hero-секції |
| `description` | Text | Повний опис |
| `short_description` | String(500) | Короткий опис для карток |
| `event_type` | String(30) | Тип: seminar, webinar, course, masterclass, conference |
| `format` | String(20) | Формат: online, offline, hybrid |
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

### Trainer

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
| `created_at` | DateTime (UTC) | Дата створення |
| `updated_at` | DateTime (UTC) | Дата оновлення |

### ProgramBlock

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BigInteger | Первинний ключ |
| `event_id` | FK -> events.id | Захід |
| `heading` | String(200) | Заголовок блоку ("Теоретична частина", ...) |
| `items` | JSON | Масив пунктів програми |
| `sort_order` | Integer | Порядок відображення |

### Зв'язки

```
User 1--* Event          (created_by)
Trainer 1--* Event       (trainer_id)
Event 1--* ProgramBlock  (event_id, cascade delete)
```

## Встановлення та запуск

### Вимоги

- Python 3.10+

### Локальний запуск

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

# Запуск
python run.py
```

Сервер стартує на `http://localhost:5001`.

### Змінні оточення

| Змінна | Опис | За замовчуванням |
|--------|------|------------------|
| `SECRET_KEY` | Секретний ключ Flask | `dev-secret-key-change-in-production` |
| `DATABASE_URL` | URI бази даних | `sqlite:///iprm.db` |
| `FLASK_CONFIG` | Профіль конфігурації | `default` (development) |

## Сервер (VPS)

| Параметр | Значення |
|----------|----------|
| Хост | `173.242.58.186` |
| Користувач | `root` |
| SSH-ключ | `keys/iprm-key` |
| Шлях до проекту | `/var/www/iprm/` |
| Systemd-сервіс | `iprm` |
| WSGI-сервер | gunicorn |

### Підключення до сервера

```bash
ssh -i keys/iprm-key root@173.242.58.186
```

### Корисні команди на сервері

```bash
# Статус сервісу
systemctl status iprm

# Перезапуск
systemctl restart iprm

# Логи
journalctl -u iprm -f

# Шлях до проекту
cd /var/www/iprm
```

## CI/CD

Деплой автоматизований через GitHub Actions (`.github/workflows/deploy.yml`):

1. **Тригер:** push у гілку `main`
2. **Rsync** файлів на VPS (виключаючи `.git`, `keys/`, `.env`, `venv/`)
3. **Перезапуск** сервісу через systemd

### Необхідні секрети GitHub

| Секрет | Опис |
|--------|------|
| `VPS_HOST` | `173.242.58.186` |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | Вміст `keys/iprm-key` |

## Залежності

| Пакет | Версія | Призначення |
|-------|--------|-------------|
| Flask | >=3.0 | Веб-фреймворк |
| Flask-SQLAlchemy | >=3.1 | ORM |
| Flask-Login | >=0.6 | Сесії користувачів |
| Flask-WTF | >=1.2 | Форми та CSRF |
| email-validator | >=2.0 | Валідація email |
| pg8000 | >=1.31 | PostgreSQL-драйвер |
| python-dotenv | >=1.0 | Завантаження .env |
| gunicorn | >=22.0 | WSGI-сервер (prod) |
