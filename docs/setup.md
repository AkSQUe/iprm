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

## Експорт юридичних сторінок у .docx

Публічна оферта, політики та дисклеймер вивантажуються у Word на фірмовому
бланку. Текст береться з тих самих Jinja-шаблонів, що й публічні сторінки, тому
документ не розходиться із сайтом.

```bash
# Одна сторінка (файл лягає в docs/legal/)
flask legal-docx offer

# Кілька сторінок або всі одразу
flask legal-docx offer privacy --output-dir build
flask legal-docx --all

# Без підписного блоку з печаткою
flask legal-docx offer --no-seal
```

Доступні ключі: `offer`, `privacy`, `cookies`, `disclaimer`, `refund`
(див. `LEGAL_PAGES` у [app/services/legal_docx_service.py](../app/services/legal_docx_service.py)).

Верхній колонтитул (логотип, реквізити) і зображення печатки з підписом
беруться з бланка `docs/legal/Шаблон листа ІПРМ.docx`. Оформлення документа:
Times New Roman 12 pt, поля 2/1/3/2 см (ліве/праве/верхнє/нижнє).

| Параметр конфігурації | Призначення | Типове значення |
|-----------------------|-------------|-----------------|
| `LEGAL_DOCX_LETTERHEAD` | Шлях до бланка листа | `docs/legal/Шаблон листа ІПРМ.docx` |
| `LEGAL_DOCX_OUTPUT_DIR` | Тека для згенерованих файлів | `docs/legal` |
| `LEGAL_DOCX_SIGNER_TITLE` | Посада у підписному блоці | `Ректор` |
| `LEGAL_DOCX_SIGNER_NAME` | Прізвище у підписному блоці | `Заболотня Д. О.` |

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
| python-docx | >=1.1 | Експорт юридичних сторінок у .docx |
| beautifulsoup4 | >=4.12 | Розбір HTML при експорті у .docx |
