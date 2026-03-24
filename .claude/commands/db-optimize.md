Ти - експерт з проектування баз даних та SQLAlchemy ORM для Flask-проектів.

## Мета

Дослідити структуру БД, оптимізувати її та виправити всі залежності в Python-коді. Робота виконується **послідовно**: кожна зміна в моделях негайно відображається у всіх залежних `.py` файлах, шаблонах та тестах.

> **Зона відповідальності:** `app/models/`, `migrations/`, `app/*/routes.py`, `app/*/forms.py`, `tests/`, та будь-які `.py` файли, що працюють з БД.
> **НЕ чіпай:** CSS, JS, HTML-розмітку (тільки Jinja2-вирази якщо змінились імена полів).

$ARGUMENTS

Якщо аргументи не передано - провести повний аудит та оптимізацію.

## Контекст проекту

- ORM: SQLAlchemy (Flask-SQLAlchemy)
- Міграції: Flask-Migrate (Alembic)
- БД: SQLite (dev), PostgreSQL (prod, pg8000)
- Extensions: `app/extensions.py` (db, migrate, login_manager, csrf, limiter)
- Моделі: `app/models/` (окремий файл на модель, `__init__.py` з експортами)
- Mixins: `TimestampMixin` з `created_at`, `updated_at` (UTC)
- Тести: `tests/` (pytest)

## ФАЗА 1: Аудит

### 1.1 Зчитати всі моделі

Прочитай ВСІ файли в `app/models/`. Для кожної моделі задокументуй:
- Таблиця, колонки (тип, constraints, defaults)
- Relationships та foreign keys
- Індекси (явні та неявні від UNIQUE)
- Computed properties та hybrid properties

### 1.2 Зчитати всі routes та forms

Прочитай ВСІ `routes.py` та `forms.py` в кожному blueprint. Знайди:
- Які моделі імпортуються та як використовуються
- Які поля читаються/записуються
- Які запити виконуються (filter, order_by, join)
- Які relationships використовуються в шаблонах (через Jinja2)

### 1.3 Зчитати міграції

Прочитай `migrations/versions/` для розуміння еволюції схеми.

### 1.4 Зчитати шаблони (лише Jinja2-вирази)

Grep по `app/templates/` для:
- `{{ model.field }}` -- які поля моделей використовуються в шаблонах
- `{% for item in model.relationship %}` -- які relationships
- `url_for()` з параметрами моделей

### 1.5 Побудувати звіт

```
=== DB AUDIT ===

--- Моделі ---
Model (table): N колонок, M relationships, K індексів

--- Проблеми ---
[INDEX]     events.start_date -- використовується в order_by (courses/routes.py:12), немає індексу
[N+1]       admin/routes.py:73 -- Event.query.all() + шаблон звертається до event.trainer
[CONSTRAINT] events.status -- немає CHECK constraint, валідація лише на рівні форм
[CASCADE]   events.created_by -> users.id -- немає ondelete правила
[NORMALIZE] user phone в event_registrations -- дублюється з кожною реєстрацією
[DEAD]      model.field -- визначено в моделі, не використовується ніде
[MISSING]   PaymentTransaction -- LiqPay інтеграція є, таблиця транзакцій відсутня

--- Зведення ---
Індексів відсутніх: N
N+1 паттернів: N
Constraints відсутніх: N
Нормалізація потрібна: N
```

## ФАЗА 2: Планування

### 2.1 Створити TODO-план

На основі аудиту створи TODO-план з чіткою послідовністю. Кожен крок = атомарна зміна, що не ламає додаток.

**Принцип послідовності:**
1. Зміна в моделі
2. Створення міграції
3. Оновлення ВСІХ `.py` файлів, що використовують цю модель (routes, forms, cli, utils)
4. Оновлення Jinja2-виразів в шаблонах (якщо змінились поля)
5. Оновлення/створення тестів
6. Верифікація -- перевірка що все компілюється та тести проходять

**Порядок виконання:**
1. Спочатку -- безпечні зміни (додавання індексів, constraints)
2. Потім -- нові моделі (не ламають існуючий код)
3. Далі -- нормалізація/розділення таблиць (потребує оновлення коду)
4. В кінці -- N+1 фікси (потребує зміни запитів)

### 2.2 Показати план користувачу

Вивести план та чекати підтвердження перед початком реалізації.

## ФАЗА 3: Реалізація

Для КОЖНОГО кроку з плану виконуй строго послідовно:

### 3.1 Зміна моделі

- Редагуй файл в `app/models/`
- Оновлюй `app/models/__init__.py` якщо додано нову модель
- Дотримуйся конвенцій:
  - BigInteger для PK
  - TimestampMixin для created_at/updated_at
  - `db.DateTime(timezone=True)` для дат
  - Явні `index=True` для часто фільтрованих колонок
  - `__tablename__` завжди в snake_case множині

### 3.2 Міграція

- Генеруй через `flask db migrate -m "опис"` якщо можливо
- Або створюй вручну якщо автогенерація не справляється
- Перевіряй що міграція працює і в SQLite, і в PostgreSQL
- НЕ використовуй PostgreSQL-специфічний SQL без перевірки dialect

### 3.3 Оновлення залежностей

Знайди ВСІ файли, що посилаються на змінену модель/поле:

```
grep -r "ModelName" app/ --include="*.py"
grep -r "old_field_name" app/ --include="*.py"
grep -r "old_field_name" app/templates/ --include="*.html"
```

Оновлюй:
- `routes.py` -- запити, фільтри, order_by, joinedload
- `forms.py` -- поля форм, валідація, populate_obj
- `__init__.py` -- імпорти
- Шаблони -- Jinja2-вирази ({{ model.field }})
- CLI commands -- якщо є seed/import команди
- Utils -- якщо є допоміжні функції

### 3.4 Тести

**ОБОВ'ЯЗКОВО:** Всі тести, що створюються цим skill, складаються в окрему папку `tests/test_db/` з чіткою структурою по категоріях. НЕ змішуй з іншими тестами в `tests/test_models/` або `tests/test_routes/` -- вони можуть містити тести написані вручну або іншими skill.

**Структура тестів db-optimize:**
```
tests/
  conftest.py              -- спільні fixtures (app, db, client)
  test_db/                 -- ВСІ тести db-optimize ТІЛЬКИ тут
    __init__.py
    conftest.py            -- fixtures специфічні для db-тестів (seed data, helpers)
    test_constraints.py    -- CHECK constraints, UNIQUE, NOT NULL, FK ondelete
    test_relationships.py  -- back_populates, cascade, lazy loading
    test_queries.py        -- joinedload, selectinload, N+1 фікси, фільтри
    test_indexes.py        -- перевірка що індексовані поля працюють в order_by/filter
```

**Кожен файл відповідає за свою категорію:**

`test_constraints.py` -- перевірка що DB-level constraints працюють:
```python
def test_event_price_non_negative(db_session):
    """CHECK constraint: price >= 0."""

def test_registration_unique_per_event(db_session):
    """UNIQUE constraint: один користувач -- одна реєстрація."""

def test_event_status_check_constraint(db_session):
    """CHECK constraint: status тільки з дозволеного списку."""
```

`test_relationships.py` -- перевірка зв'язків між моделями:
```python
def test_event_trainer_back_populates(db_session):
    """Двосторонній зв'язок Event <-> Trainer."""

def test_event_cascade_deletes_program_blocks(db_session):
    """CASCADE: видалення event видаляє program_blocks."""

def test_registration_back_populates_user_and_event(db_session):
    """Двосторонній зв'язок EventRegistration <-> User/Event."""
```

`test_queries.py` -- перевірка оптимізованих запитів:
```python
def test_events_list_with_joinedload_trainer(db_session):
    """joinedload(Event.trainer) не ламає запит."""

def test_registrations_with_joinedload_user(db_session):
    """joinedload(EventRegistration.user) не ламає запит."""
```

`test_indexes.py` -- перевірка що індексовані колонки працюють коректно:
```python
def test_events_order_by_start_date(db_session):
    """Сортування по індексованому start_date."""

def test_trainers_order_by_full_name(db_session):
    """Сортування по індексованому full_name."""
```

**Правила:**
- Кожен тестовий файл має `__init__.py` в своїй папці
- Спільні fixtures (створення user, event, trainer) виносяться в `tests/test_db/conftest.py`
- Назви тестів описують ЩО перевіряється, а не ЯК
- Docstring кожного тесту пояснює бізнес-правило або constraint

### 3.5 Позначити крок завершеним

Позначити TODO як completed тільки після:
- Модель оновлена
- Всі залежні .py файли оновлені
- Шаблони оновлені (якщо потрібно)
- Тести написані та проходять

## ФАЗА 4: Верифікація

Після завершення ВСІХ кроків:

### 4.1 Компіляція

```bash
python -c "from app import create_app; app = create_app('testing')"
```

Перевір що додаток стартує без помилок.

### 4.2 Тести

```bash
python -m pytest tests/ -v
```

Всі тести мають проходити.

### 4.3 Перевірка міграцій

```bash
flask db upgrade   # apply all migrations
flask db downgrade # rollback
flask db upgrade   # re-apply
```

Міграції мають бути ідемпотентними.

### 4.4 Перевірка цілісності

- Кожна модель в `app/models/__init__.py` має правильний імпорт
- Кожен blueprint імпортує потрібні моделі
- Жоден файл не посилається на видалені/перейменовані поля
- Всі relationships двосторонні (back_populates або backref)
- Всі FK мають явне ondelete правило
- Всі часто фільтровані колонки мають індекси

### 4.5 Фінальний звіт

```
=== DB OPTIMIZATION COMPLETE ===

--- Виконано ---
[+] Додано N індексів
[+] Додано N CHECK constraints
[+] Виправлено N N+1 запитів
[+] Створено N нових моделей
[+] Нормалізовано N таблиць
[+] Написано N тестів

--- Міграції ---
migration_001: опис
migration_002: опис

--- Залежності оновлені ---
app/admin/routes.py: N змін
app/courses/routes.py: N змін
...

--- Тести ---
Passed: N
Failed: 0
```

## Типові оптимізації

### Індекси
```python
# Одиночний індекс
status = db.Column(db.String(20), index=True)

# Складений індекс
__table_args__ = (
    db.Index('ix_events_active_status', 'is_active', 'status'),
)
```

### CHECK constraints
```python
__table_args__ = (
    db.CheckConstraint(
        "status IN ('draft', 'published', 'active', 'completed', 'cancelled')",
        name='ck_events_status'
    ),
)
```

### CASCADE правила
```python
created_by = db.Column(db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
event_id = db.Column(db.BigInteger, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
```

### N+1 фікси
```python
from sqlalchemy.orm import joinedload, selectinload

# Для single object relationships (many-to-one)
events = Event.query.options(joinedload(Event.trainer)).all()

# Для collection relationships (one-to-many)
events = Event.query.options(selectinload(Event.program_blocks)).all()
```

### Нормалізація
```python
# Якщо поле дублюється в кількох записах -- виноси в окрему таблицю
# Старий підхід:
class EventRegistration:
    phone = db.Column(db.String(20))  # дублюється для кожної реєстрації

# Новий підхід:
class UserProfile:
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    phone = db.Column(db.String(20))
```

## Обмеження

- НЕ видаляй дані або таблиці без явного підтвердження користувача
- НЕ змінюй CSS/JS/HTML-розмітку -- тільки Jinja2-вирази при зміні полів моделей
- НЕ використовуй PostgreSQL-специфічний синтаксис без перевірки на SQLite
- НЕ створюй міграції з `render_as_batch=False` (потрібно для SQLite)
- НЕ ламай backward compatibility міграцій (кожна має upgrade + downgrade)
- НЕ пропускай оновлення залежностей -- кожна зміна моделі має негайний каскад на весь код
- Пиши коментарі та commit-повідомлення українською
- Кожен крок має залишати додаток у робочому стані
