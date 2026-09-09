# Довідник видів заходів БПР — план реалізації

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Замінити п'ять захардкожених типів курсу на редагований довідник із 12 видів заходів БПР, з перекладами, відмінками для сертифікатів і необов'язковим перевизначенням типу в проведенні.

**Architecture:** Нова таблиця `event_types` з природним ключем `code`; `courses.event_type` лишається рядком і посилається на цей код, тому контракти API, xlsx і тестових фікстур не змінюються. Служба `app/services/event_types.py` тримає весь довідник у `g` на час запиту (дзеркало `city_glossary`) і віддає назви, відмінки та `choices` для форм. Сторінка `/admin/event-types` побудована за взірцем довідника локацій.

**Tech Stack:** Flask, SQLAlchemy, Alembic, WTForms, Jinja2, pytest.

**Spec:** [docs/superpowers/specs/2026-09-09-bpr-event-types-design.md](../specs/2026-09-09-bpr-event-types-design.md)

## Global Constraints

- Мова коментарів і рядків інтерфейсу — українська; емодзі в коді заборонені (CLAUDE.md).
- Жодного inline-CSS і inline-JS: стилі — окремим файлом, класи — з дизайн-системи (CLAUDE.md, «No Inline Policy»).
- Сторінковий CSS зветься `page-*.css` і містить лише layout; декор бере з `admin.css` (CLAUDE.md, «Дизайн-система — джерело істини»).
- Робота йде в ізольованому worktree `D:/site-iprm-wt-bpr-event-types` на гілці `sdd/bpr-event-types`; коміти лягають туди. Це свідомий тимчасовий відступ від проєктного правила «прямо в main, без фіча-гілок»: у головному дереві паралельно працює інший SDD-прогін. Злиття в `main` робиться наприкінці, `git push` — тільки людиною.
- `git add` завжди перелічує конкретні шляхи, ніколи `-A` і не `.`.
- Одна alembic-ревізія на всю задачу. Поточна голова — `transfer_after_days_20260908`.
- Міграції, що чіпають CHECK-констрейнти, обгортаються `if bind.dialect.name != 'sqlite'` — так уже зроблено в `b5e2a1d34f87_add_indexes_check_constraints.py`.
- Тести прибирають за собою рядки довідника: таблиця глобальна на всю сесію pytest.

---

## Структура файлів

**Створюються:**

| Файл | Відповідальність |
|---|---|
| `app/models/event_type.py` | модель `EventType` + канонічний `SEED_ROWS` |
| `app/services/event_types.py` | читання довідника, кеш у `g`, назви/відмінки/choices/usage |
| `migrations/versions/bpr_event_types_20260909.py` | таблиця, сидінг, зняття CHECK, колонка проведення |
| `app/admin/routes_event_types.py` | сторінка довідника (list/save/add/delete) |
| `app/templates/admin/event_types.html` | розмітка сторінки |
| `app/static/css/page-admin-event-types.css` | ширини колонок таблиці, і більш нічого |
| `tests/test_models/test_event_type.py` | модель і цілісність сидінгу |
| `tests/test_services/test_event_types.py` | служба |
| `tests/test_routes/test_admin_event_types.py` | адмінка |
| `tests/test_db/test_migration_bpr_event_types.py` | сидінг міграції |

**Змінюються:**

| Файл | Що саме |
|---|---|
| `app/models/__init__.py` | експорт `EventType` |
| `app/models/course.py:105` | прибрати `CheckConstraint('ck_courses_event_type')` |
| `app/models/course.py:173-189` | прибрати `EVENT_TYPES`, `event_type_label` через службу |
| `app/models/course_instance.py` | колонка `event_type`, `effective_event_type`, `event_type_label` |
| `app/admin/routes.py:7` | імпорт нового модуля роутів |
| `app/rbac/registry.py:72` | новий `Module('event_types', …)` |
| `app/templates/admin/partials/_sidebar.html:40` | пункт сайдбару |
| `app/admin/forms.py:464` | `event_type` без статичних `choices` |
| `app/admin/forms.py:719` | `event_type` у формі проведення |
| `app/admin/routes_courses.py:87,130` | заповнення `choices` |
| `app/admin/routes_instances.py` | заповнення `choices` проведення |
| `app/services/certificate_service.py:197,369-388,726` | відмінки з довідника |
| `app/services/xlsx_io.py:227-232,797-800,922` | валідація і drop-down з довідника |
| `app/courses/routes.py:140` | ефективний тип у розкладі |
| `tests/conftest.py:44` | сидінг довідника + скидання кешу між тестами |

Ефективний тип проведення — властивість моделі `CourseInstance.effective_event_type`, а не функція служби; спеку приведено до цього ж формулювання.

---

### Task 1: Модель `EventType`, міграція, сидінг

**Files:**
- Create: `app/models/event_type.py`
- Create: `migrations/versions/bpr_event_types_20260909.py`
- Create: `tests/test_models/test_event_type.py`
- Create: `tests/test_db/test_migration_bpr_event_types.py`
- Modify: `app/models/__init__.py`
- Modify: `app/models/course.py` (зняти CHECK)
- Modify: `app/models/course_instance.py` (колонка `event_type`)
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: нічого.
- Produces: `EventType` з полями `code: str`, `name: str`, `name_accusative: str | None`, `name_genitive: str | None`, `sort_order: int`, `is_active: bool`, `t(field, lang=None) -> str`; константа `SEED_ROWS: tuple[dict, ...]`; колонка `CourseInstance.event_type: str | None`.

- [ ] **Step 1: Написати тести моделі й сидінгу**

Створити `tests/test_models/test_event_type.py`:

```python
"""Довідник видів заходів: цілісність сидінгу і переклади."""
from uuid import uuid4

from app.extensions import db
from app.models.event_type import SEED_ROWS, EventType

LEGACY = {'course', 'webinar', 'conference'}


def test_seed_has_twelve_active_and_three_legacy():
    active = [r for r in SEED_ROWS if r['is_active']]
    legacy = [r for r in SEED_ROWS if not r['is_active']]
    assert len(active) == 12
    assert {r['code'] for r in legacy} == LEGACY


def test_seed_codes_unique_and_active_order_is_dense():
    codes = [r['code'] for r in SEED_ROWS]
    assert len(codes) == len(set(codes))
    active = [r for r in SEED_ROWS if r['is_active']]
    assert [r['sort_order'] for r in active] == list(range(1, 13))


def test_seed_keeps_existing_codes_active():
    """seminar і masterclass уже стоять у даних -- вони мусять лишитись
    активними, інакше наявні курси втратять чинний тип."""
    active = {r['code'] for r in SEED_ROWS if r['is_active']}
    assert {'seminar', 'masterclass'} <= active


def test_every_seed_row_carries_both_cases_in_lower():
    for row in SEED_ROWS:
        assert row['name_accusative'], row['code']
        assert row['name_genitive'], row['code']
        assert row['name_accusative'][0].islower(), row['code']
        assert row['name_genitive'][0].islower(), row['code']
        assert row['name'][0].isupper(), row['code']


def test_translation_falls_back_to_ukrainian(db_session):
    row = EventType(code=f't-{uuid4().hex[:6]}', name='Тест', sort_order=99)
    db.session.add(row)
    db.session.flush()

    assert row.t('name') == 'Тест'
    assert row.t('name', 'en') == 'Тест'

    row.set_translation('en', 'name', 'Test')
    assert row.t('name', 'en') == 'Test'
```

Створити `tests/test_db/test_migration_bpr_event_types.py`:

```python
"""Міграція bpr_event_types_20260909: сидінг довідника.

DDL тут не проганяємо -- у тестовій схемі (create_all з моделей) таблиця
вже є. Перевіряємо те, де справді можна помилитись: список рядків, який
міграція вставляє, мусить збігатися з канонічним SEED_ROWS моделі.
Розійдуться -- прод отримає одне наповнення, а тести інше.
"""
import importlib.util
from pathlib import Path

import pytest

from app.models.event_type import SEED_ROWS

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / 'migrations' / 'versions' / 'bpr_event_types_20260909.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_bpr_event_types', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_seed_matches_model_seed(migration):
    def key(rows):
        return sorted(
            (r['code'], r['name'], r['name_accusative'],
             r['name_genitive'], r['sort_order'], r['is_active'])
            for r in rows
        )

    assert key(migration.SEED_ROWS) == key(SEED_ROWS)


def test_migration_declares_current_head(migration):
    assert migration.down_revision == 'transfer_after_days_20260908'
    assert migration.revision == 'bpr_event_types_20260909'
```

- [ ] **Step 2: Прогнати тести й переконатись, що вони падають**

Run: `python -m pytest tests/test_models/test_event_type.py tests/test_db/test_migration_bpr_event_types.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.models.event_type'`

- [ ] **Step 3: Створити модель із канонічним сидінгом**

Створити `app/models/event_type.py`:

```python
"""Довідник видів заходів БПР.

Вид заходу друкується в сертифікаті й іде у звітність, тож перелік має
збігатися з нормативною номенклатурою. Тримати його константою в коді
означало б деплой на кожну зміну номенклатури -- тому це таблиця з
власною сторінкою в адмінці.

Курс посилається сюди КОДОМ (courses.event_type -- рядок), а не через FK:
код уже їде в партнерське API та в xlsx, і заміна його на id зламала б
обидва контракти заради цілісності, яку тут дає заборона видаляти
вживаний рядок.

Тип, якого більше немає в номенклатурі, не видаляється й не
перемапується -- йому знімають is_active. Тоді він зникає з вибору, але
курси, де він уже стоїть, показуються як раніше.
"""
from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin, TranslatableMixin


class EventType(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'event_types'
    __translatable__ = ('name',)

    id = db.Column(BigIntPK, primary_key=True)

    # Стабільний ключ. Саме його зберігає courses.event_type і віддає API.
    code = db.Column(db.String(30), unique=True, nullable=False)

    # Називний, з великої -- це бейдж на картці курсу.
    name = db.Column(db.String(120), nullable=False)

    # Відмінки друкуються всередині речення сертифіката, тож зберігаються
    # з малої. Знахідний: "успішно завершив(-ла) наукову конференцію".
    # Родовий: "лектору(-ці) наукової конференції".
    name_accusative = db.Column(db.String(120))
    name_genitive = db.Column(db.String(120))

    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    def __repr__(self):
        return f'<EventType {self.code}>'


# Канонічна номенклатура. Звідси сідається тестова схема (create_all не
# знає про міграції) і звідси ж копіювався сидінг міграції.
SEED_ROWS = (
    {'code': 'seminar', 'name': 'Семінар',
     'name_accusative': 'семінар', 'name_genitive': 'семінару',
     'sort_order': 1, 'is_active': True},
    {'code': 'scientific_conference', 'name': 'Наукова конференція',
     'name_accusative': 'наукову конференцію',
     'name_genitive': 'наукової конференції',
     'sort_order': 2, 'is_active': True},
    {'code': 'elearning_course', 'name': 'Електронний навчальний курс',
     'name_accusative': 'електронний навчальний курс',
     'name_genitive': 'електронного навчального курсу',
     'sort_order': 3, 'is_active': True},
    {'code': 'congress', 'name': 'Конгрес',
     'name_accusative': 'конгрес', 'name_genitive': 'конгресу',
     'sort_order': 4, 'is_active': True},
    {'code': 'practical_conference', 'name': 'Науково-практична конференція',
     'name_accusative': 'науково-практичну конференцію',
     'name_genitive': 'науково-практичної конференції',
     'sort_order': 5, 'is_active': True},
    {'code': 'symposium', 'name': 'Симпозіум',
     'name_accusative': 'симпозіум', 'name_genitive': 'симпозіуму',
     'sort_order': 6, 'is_active': True},
    {'code': 'convention', 'name': 'З\'їзд',
     'name_accusative': 'з\'їзд', 'name_genitive': 'з\'їзду',
     'sort_order': 7, 'is_active': True},
    {'code': 'simulation_training', 'name': 'Симуляційний тренінг',
     'name_accusative': 'симуляційний тренінг',
     'name_genitive': 'симуляційного тренінгу',
     'sort_order': 8, 'is_active': True},
    {'code': 'skills_training',
     'name': 'Тренінг з оволодіння практичними навичками',
     'name_accusative': 'тренінг з оволодіння практичними навичками',
     'name_genitive': 'тренінгу з оволодіння практичними навичками',
     'sort_order': 9, 'is_active': True},
    {'code': 'training', 'name': 'Тренінг',
     'name_accusative': 'тренінг', 'name_genitive': 'тренінгу',
     'sort_order': 10, 'is_active': True},
    {'code': 'masterclass', 'name': 'Майстер-клас',
     'name_accusative': 'майстер-клас', 'name_genitive': 'майстер-класу',
     'sort_order': 11, 'is_active': True},
    {'code': 'professional_school', 'name': 'Фахова (тематична) школа',
     'name_accusative': 'фахову (тематичну) школу',
     'name_genitive': 'фахової (тематичної) школи',
     'sort_order': 12, 'is_active': True},

    # Застарілі: у номенклатурі БПР їх немає, але вони стоять у наявних
    # курсах. Лишаються рядками, щоб ті курси не показували голий код.
    {'code': 'course', 'name': 'Курс',
     'name_accusative': 'курс', 'name_genitive': 'курсу',
     'sort_order': 90, 'is_active': False},
    {'code': 'webinar', 'name': 'Вебінар',
     'name_accusative': 'вебінар', 'name_genitive': 'вебінару',
     'sort_order': 91, 'is_active': False},
    {'code': 'conference', 'name': 'Конференція',
     'name_accusative': 'конференцію', 'name_genitive': 'конференції',
     'sort_order': 92, 'is_active': False},
)
```

- [ ] **Step 4: Зареєструвати модель в `app/models/__init__.py`**

Поруч із `from app.models.city import City` (рядок 41) додати:

```python
from app.models.event_type import EventType
```

і в список `__all__` (поруч із `'City'`, рядок 66) додати `'EventType',`.

- [ ] **Step 5: Зняти CHECK із моделі курсу і додати колонку проведенню**

У `app/models/course.py`, у `__table_args__`, видалити блок:

```python
        db.CheckConstraint(
            "event_type IN ('seminar', 'webinar', 'course', 'masterclass', 'conference')",
            name='ck_courses_event_type',
        ),
```

Це обов'язково: тестова схема будується `create_all()` з моделей, і залишений CHECK не пустив би жоден новий код.

У `app/models/course_instance.py`, поруч із `event_format` (рядок 28), додати:

```python
    # Перевизначення виду заходу для конкретного проведення. Порожньо --
    # береться тип курсу (див. effective_event_type). Потрібне, коли той
    # самий курс раз проводять тренінгом, а раз -- фаховою школою.
    event_type = db.Column(db.String(30))
```

- [ ] **Step 6: Написати міграцію**

Створити `migrations/versions/bpr_event_types_20260909.py`:

```python
"""Довідник видів заходів БПР

Revision ID: bpr_event_types_20260909
Revises: transfer_after_days_20260908
Create Date: 2026-09-09 00:00:00.000000

Створює таблицю event_types, сідає номенклатуру, знімає CHECK із
courses.event_type і додає перевизначення типу проведенню.
"""
from alembic import op
import sqlalchemy as sa


revision = 'bpr_event_types_20260909'
down_revision = 'transfer_after_days_20260908'
branch_labels = None
depends_on = None


# Копія app.models.event_type.SEED_ROWS, свідома: міграція -- застигла
# історія, і імпорт з моделі означав би, що вже застосована ревізія
# змінює поведінку разом із наступними правками номенклатури.
# Розбіжність ловить tests/test_db/test_migration_bpr_event_types.py.
SEED_ROWS = (
    {'code': 'seminar', 'name': 'Семінар',
     'name_accusative': 'семінар', 'name_genitive': 'семінару',
     'sort_order': 1, 'is_active': True},
    {'code': 'scientific_conference', 'name': 'Наукова конференція',
     'name_accusative': 'наукову конференцію',
     'name_genitive': 'наукової конференції',
     'sort_order': 2, 'is_active': True},
    {'code': 'elearning_course', 'name': 'Електронний навчальний курс',
     'name_accusative': 'електронний навчальний курс',
     'name_genitive': 'електронного навчального курсу',
     'sort_order': 3, 'is_active': True},
    {'code': 'congress', 'name': 'Конгрес',
     'name_accusative': 'конгрес', 'name_genitive': 'конгресу',
     'sort_order': 4, 'is_active': True},
    {'code': 'practical_conference', 'name': 'Науково-практична конференція',
     'name_accusative': 'науково-практичну конференцію',
     'name_genitive': 'науково-практичної конференції',
     'sort_order': 5, 'is_active': True},
    {'code': 'symposium', 'name': 'Симпозіум',
     'name_accusative': 'симпозіум', 'name_genitive': 'симпозіуму',
     'sort_order': 6, 'is_active': True},
    {'code': 'convention', 'name': 'З\'їзд',
     'name_accusative': 'з\'їзд', 'name_genitive': 'з\'їзду',
     'sort_order': 7, 'is_active': True},
    {'code': 'simulation_training', 'name': 'Симуляційний тренінг',
     'name_accusative': 'симуляційний тренінг',
     'name_genitive': 'симуляційного тренінгу',
     'sort_order': 8, 'is_active': True},
    {'code': 'skills_training',
     'name': 'Тренінг з оволодіння практичними навичками',
     'name_accusative': 'тренінг з оволодіння практичними навичками',
     'name_genitive': 'тренінгу з оволодіння практичними навичками',
     'sort_order': 9, 'is_active': True},
    {'code': 'training', 'name': 'Тренінг',
     'name_accusative': 'тренінг', 'name_genitive': 'тренінгу',
     'sort_order': 10, 'is_active': True},
    {'code': 'masterclass', 'name': 'Майстер-клас',
     'name_accusative': 'майстер-клас', 'name_genitive': 'майстер-класу',
     'sort_order': 11, 'is_active': True},
    {'code': 'professional_school', 'name': 'Фахова (тематична) школа',
     'name_accusative': 'фахову (тематичну) школу',
     'name_genitive': 'фахової (тематичної) школи',
     'sort_order': 12, 'is_active': True},
    {'code': 'course', 'name': 'Курс',
     'name_accusative': 'курс', 'name_genitive': 'курсу',
     'sort_order': 90, 'is_active': False},
    {'code': 'webinar', 'name': 'Вебінар',
     'name_accusative': 'вебінар', 'name_genitive': 'вебінару',
     'sort_order': 91, 'is_active': False},
    {'code': 'conference', 'name': 'Конференція',
     'name_accusative': 'конференцію', 'name_genitive': 'конференції',
     'sort_order': 92, 'is_active': False},
)


def upgrade():
    event_types = op.create_table(
        'event_types',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('name_accusative', sa.String(length=120), nullable=True),
        sa.Column('name_genitive', sa.String(length=120), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('translations', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_event_types_code'),
    )
    op.create_index('ix_event_types_is_active', 'event_types', ['is_active'])
    op.bulk_insert(event_types, [dict(row) for row in SEED_ROWS])

    # CHECK перелічував п'ять старих кодів. Тепер перелік живе в довіднику,
    # а не в схемі: інакше кожна зміна номенклатури тягла б міграцію, чого
    # ця задача якраз і позбувається.
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.drop_constraint('ck_courses_event_type', 'courses', type_='check')

    op.add_column('course_instances',
                  sa.Column('event_type', sa.String(length=30), nullable=True))


def downgrade():
    op.drop_column('course_instances', 'event_type')

    # Односторонній крок: курси, яким уже проставили новий код
    # (congress, convention, ...), цей CHECK не пройдуть. Перед відкатом
    # такі курси треба повернути на старі п'ять кодів вручну.
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.create_check_constraint(
            'ck_courses_event_type', 'courses',
            "event_type IN ('seminar', 'webinar', 'course', 'masterclass', 'conference')",
        )

    op.drop_index('ix_event_types_is_active', table_name='event_types')
    op.drop_table('event_types')
```

- [ ] **Step 7: Засіяти довідник у тестовій схемі**

`tests/conftest.py` будує схему через `create_all()`, тобто без міграції — довідник був би порожній, і `event_type_label` у наявних тестах повертав би голий код замість «Курс».

У фікстурі `app` (рядок 44), одразу після `rbac_service.sync()`, додати:

```python
        from app.models.event_type import SEED_ROWS, EventType
        for row in SEED_ROWS:
            if not EventType.query.filter_by(code=row['code']).first():
                _db.session.add(EventType(**row))
```

- [ ] **Step 8: Прогнати тести**

Run: `python -m pytest tests/test_models/test_event_type.py tests/test_db/test_migration_bpr_event_types.py -v`
Expected: PASS (усі 6 тестів)

- [ ] **Step 9: Переконатися, що наявна схема не поламалась**

Run: `python -m pytest tests/test_db tests/test_models -q`
Expected: PASS, усе без винятків. Ця задача не чіпає ні `Course.EVENT_TYPES`, ні `event_type_label`, тож `test_course_event_type_label` і далі проходить через стару константу. Якщо щось упало — це реальна регресія від зняття CHECK або від сидінгу: спинитись і розібратись, а не правити тест.

- [ ] **Step 10: Застосувати міграцію на dev-БД**

Run: `python -m flask db upgrade`
Then: `python -m flask db heads`
Expected: одна голова, `bpr_event_types_20260909 (head)`

- [ ] **Step 11: Коміт**

```bash
git add app/models/event_type.py app/models/__init__.py app/models/course.py \
        app/models/course_instance.py migrations/versions/bpr_event_types_20260909.py \
        tests/test_models/test_event_type.py tests/test_db/test_migration_bpr_event_types.py \
        tests/conftest.py
git commit -m "feat(courses): таблиця довідника видів заходів БПР"
```

---

### Task 2: Служба `app/services/event_types.py`

**Files:**
- Create: `app/services/event_types.py`
- Create: `tests/test_services/test_event_types.py`
- Modify: `tests/conftest.py` (скидання кешу між тестами)

**Interfaces:**
- Consumes: `EventType`, `SEED_ROWS` з Task 1.
- Produces:
  - `directory() -> dict[str, EventType]` — код → рядок, у порядку `sort_order`
  - `label(code: str | None) -> str | None` — назва активною мовою; невідомий код повертається як є
  - `accusative(code: str | None) -> str | None`
  - `genitive(code: str | None) -> str | None`
  - `choices(current: str | None = None) -> list[tuple[str, str]]`
  - `usage() -> dict[str, int]`
  - `reset_cache() -> None`

- [ ] **Step 1: Написати тести служби**

Створити `tests/test_services/test_event_types.py`:

```python
"""Служба довідника видів заходів: назви, відмінки, choices, usage."""
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.event_type import EventType
from app.services import event_types


def _custom(code=None, **kw):
    """Власний рядок довідника. Прибираємо за собою: таблиця глобальна."""
    row = EventType(code=code or f'z-{uuid4().hex[:6]}',
                    name=kw.pop('name', 'Тестовий тип'),
                    sort_order=kw.pop('sort_order', 500), **kw)
    db.session.add(row)
    db.session.flush()
    event_types.reset_cache()
    return row


def test_label_returns_seeded_name(app):
    assert event_types.label('seminar') == 'Семінар'


def test_label_of_unknown_code_returns_the_code(app):
    assert event_types.label('no-such-type') == 'no-such-type'


def test_label_of_empty_code_is_empty(app):
    assert event_types.label(None) is None
    assert event_types.label('') == ''


def test_label_uses_translation_when_present(app, db_session):
    row = _custom(name='Тренінг')
    row.set_translation('en', 'name', 'Training')
    event_types.reset_cache()

    assert event_types.label(row.code, lang='en') == 'Training'
    assert event_types.label(row.code, lang='ru') == 'Тренінг'


def test_accusative_and_genitive_come_from_directory(app):
    assert event_types.accusative('scientific_conference') == 'наукову конференцію'
    assert event_types.genitive('scientific_conference') == 'наукової конференції'


def test_cases_fall_back_to_lowered_name(app, db_session):
    row = _custom(name='Вебмарафон')
    assert event_types.accusative(row.code) == 'вебмарафон'
    assert event_types.genitive(row.code) == 'вебмарафон'


def test_cases_of_unknown_code_fall_back_to_the_code(app):
    assert event_types.accusative('mystery') == 'mystery'
    assert event_types.genitive(None) is None


def test_choices_hold_active_types_in_seed_order(app):
    codes = [code for code, _ in event_types.choices()]
    assert codes[:3] == ['seminar', 'scientific_conference', 'elearning_course']
    assert 'course' not in codes, 'застарілий тип не пропонується у виборі'


def test_choices_add_current_even_when_deactivated(app):
    codes = dict(event_types.choices(current='course'))
    assert 'course' in codes
    assert 'застарілий' in codes['course']


def test_choices_do_not_duplicate_current_when_active(app):
    codes = [code for code, _ in event_types.choices(current='seminar')]
    assert codes.count('seminar') == 1


def test_usage_counts_courses_by_code(app, db_session):
    slug = f'u-{uuid4().hex[:6]}'
    db.session.add(Course(title='К', slug=slug, event_type='symposium'))
    db.session.flush()

    assert event_types.usage().get('symposium', 0) >= 1
```

- [ ] **Step 2: Прогнати тести й переконатись, що вони падають**

Run: `python -m pytest tests/test_services/test_event_types.py -v`
Expected: FAIL, `ImportError: cannot import name 'event_types' from 'app.services'`

- [ ] **Step 3: Написати службу**

Створити `app/services/event_types.py`:

```python
"""Читання довідника видів заходів БПР.

Довідник крихітний (півтора десятка рядків), а звертань до нього багато:
кожна картка курсу, кожен рядок розкладу, кожен сертифікат. Тому він
читається ЦІЛКОМ одним запитом і кладеться в g на час HTTP-запиту --
інакше сторінка розкладу з десятком проведень дала б десяток запитів.
Той самий підхід, що в app/services/city_glossary.py.

Довідник -- шар назв поверх коду, а не джерело істини про курс. Якщо
таблиці ще немає (код піднявся раніше за міграцію) або БД моргнула, ми
показуємо сирий код і пишемо в лог, але публічну сторінку не кладемо.
"""
import logging

from flask import g, has_app_context

logger = logging.getLogger(__name__)

_CACHE_ATTR = '_event_type_directory'


def reset_cache():
    """Забути закешований довідник. Потрібно після правки рядків в
    адмінці й між тестами: app-контекст у тестах один на всю сесію, тож
    без цього доданий тип не побачила б наступна перевірка."""
    if has_app_context():
        g.pop(_CACHE_ATTR, None)


def directory():
    """{code: EventType} у порядку sort_order -- один запит на запит."""
    if has_app_context() and _CACHE_ATTR in g:
        return g.get(_CACHE_ATTR)

    from app.models.event_type import EventType
    try:
        rows = EventType.query.order_by(
            EventType.sort_order, EventType.name).all()
        mapping = {row.code: row for row in rows}
    except Exception:
        logger.exception('Event type directory unavailable, falling back to raw codes')
        mapping = {}

    if has_app_context():
        setattr(g, _CACHE_ATTR, mapping)
    return mapping


def label(code, lang=None):
    """Назва активною (або заданою) мовою. Немає в довіднику -- сам код."""
    if not code:
        return code
    row = directory().get(code)
    return row.t('name', lang) if row is not None else code


def accusative(code):
    """Знахідний для сертифіката учасника: "завершив(-ла) <accusative>"."""
    return _case(code, 'name_accusative')


def genitive(code):
    """Родовий для лекторського сертифіката: "лектору(-ці) <genitive>"."""
    return _case(code, 'name_genitive')


def _case(code, field):
    """Відмінок із довідника; немає -- називний з малої; немає рядка --
    сам код. Порожній код лишається порожнім: шаблон сертифіката тоді
    друкує запасне "захід"/"заходу"."""
    if not code:
        return code
    row = directory().get(code)
    if row is None:
        return code.lower()
    return getattr(row, field) or row.name.lower()


def choices(current=None):
    """Пари для SelectField: активні типи плюс current, навіть якщо той
    деактивований.

    Без домішування current WTForms відхилив би сабміт старого курсу з
    "Not a valid choice", і адміністратор не зберіг би навіть правку
    заголовка, що типу не стосується.
    """
    rows = directory()
    items = [(code, row.name) for code, row in rows.items() if row.is_active]
    if current and not any(code == current for code, _ in items):
        row = rows.get(current)
        items.append((current, f'{row.name} (застарілий)' if row else current))
    return items


def usage():
    """{code: скільки курсів і проведень цим типом}.

    Адмінці це і вага рядка, і запобіжник: вживаний тип видаляти не можна,
    його деактивують.
    """
    from app.extensions import db
    from app.models.course import Course
    from app.models.course_instance import CourseInstance

    counts = {}
    for model in (Course, CourseInstance):
        rows = (
            db.session.query(model.event_type, db.func.count(model.id))
            .filter(model.event_type.isnot(None), model.event_type != '')
            .group_by(model.event_type)
            .all()
        )
        for code, count in rows:
            counts[code] = counts.get(code, 0) + count
    return counts
```

- [ ] **Step 4: Скидати кеш між тестами**

У `tests/conftest.py`, у autouse-фікстурі `db_session` (рядок 58), на самому початку тіла додати:

```python
    from app.services import event_types
    event_types.reset_cache()
```

App-контекст у тестах живе всю сесію, тож без цього рядок, доданий одним тестом, лишався б у `g` для решти — і навпаки, наступний тест не бачив би свіжих даних.

- [ ] **Step 5: Прогнати тести**

Run: `python -m pytest tests/test_services/test_event_types.py -v`
Expected: PASS (11 тестів)

- [ ] **Step 6: Коміт**

```bash
git add app/services/event_types.py tests/test_services/test_event_types.py tests/conftest.py
git commit -m "feat(courses): служба довідника видів заходів із кешем на запит"
```

---

### Task 3: Моделі-споживачі — назви через довідник

**Files:**
- Modify: `app/models/course.py:173-189`
- Modify: `app/models/course_instance.py`
- Modify: `app/courses/routes.py:140-141`
- Modify: `tests/test_models/test_course.py:19-22`
- Create: `tests/test_models/test_course_instance_event_type.py`

**Interfaces:**
- Consumes: `event_types.label` з Task 2.
- Produces:
  - `Course.event_type_label -> str | None`
  - `CourseInstance.effective_event_type -> str | None`
  - `CourseInstance.event_type_label -> str | None`
  - `Course.EVENT_TYPES` більше не існує — Tasks 5 і 7 мусять брати перелік зі служби.

- [ ] **Step 1: Написати тест перевизначення в проведенні**

Створити `tests/test_models/test_course_instance_event_type.py`:

```python
"""Тип проведення: власний перебиває курсовий, порожній -- успадковує."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance


def _pair(course_type='seminar', instance_type=None):
    course = Course(title='К', slug=f'ei-{uuid4().hex[:6]}',
                    is_active=True, event_type=course_type)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, event_type=instance_type,
        start_date=datetime.now(timezone.utc) + timedelta(days=7),
        status='published',
    )
    db.session.add(inst)
    db.session.flush()
    return course, inst


def test_instance_inherits_course_type(db_session):
    _course, inst = _pair(course_type='seminar')
    assert inst.effective_event_type == 'seminar'
    assert inst.event_type_label == 'Семінар'


def test_instance_type_overrides_course_type(db_session):
    _course, inst = _pair(course_type='seminar', instance_type='training')
    assert inst.effective_event_type == 'training'
    assert inst.event_type_label == 'Тренінг'


def test_instance_without_any_type_has_no_label(db_session):
    _course, inst = _pair(course_type=None)
    assert inst.effective_event_type is None
    assert inst.event_type_label is None


def test_deactivated_course_type_still_renders(db_session):
    """Курс зі старим типом мусить показувати «Курс», а не голий код."""
    course, inst = _pair(course_type='course')
    assert course.event_type_label == 'Курс'
    assert inst.event_type_label == 'Курс'
```

- [ ] **Step 2: Прогнати тест і переконатись, що він падає**

Run: `python -m pytest tests/test_models/test_course_instance_event_type.py -v`
Expected: FAIL, `AttributeError: 'CourseInstance' object has no attribute 'effective_event_type'`

- [ ] **Step 3: Перевести `Course` на довідник**

Константу `EVENT_TYPES` (рядки 173-179) **лишити на місці** — її прибирає Task 7, останній її споживач. Причина: `app/admin/forms.py:466` і `app/services/xlsx_io.py:227` читають її в ТІЛІ модуля, а обидва модулі імпортуються при старті застосунку. Прибрати константу тут означало б, що від кінця цієї задачі й до кінця Task 7 не запускається жоден тест — включно з перевіркою цієї ж задачі.

Замінити лише `event_type_label` (рядки 187-189) на:

```python
    @property
    def event_type_label(self):
        """Назва виду заходу з довідника, активною мовою.

        Перелік більше не константа: він живе в таблиці event_types і
        редагується в /admin/event-types.
        """
        from app.services import event_types
        return event_types.label(self.event_type)
```

- [ ] **Step 4: Додати властивості проведенню**

У `app/models/course_instance.py`, поруч із `format_label` (рядок 156), додати:

```python
    @property
    def effective_event_type(self):
        """Код виду заходу: власний, а якщо порожній -- курсовий."""
        if self.event_type:
            return self.event_type
        return self.course.event_type if self.course else None

    @property
    def event_type_label(self):
        from app.services import event_types
        return event_types.label(self.effective_event_type)
```

- [ ] **Step 5: Показати в розкладі ефективний тип**

У `app/courses/routes.py` замінити рядки 140-141:

```python
        'event_type': inst.effective_event_type,
        'event_type_label': inst.event_type_label,
```

- [ ] **Step 6: Оновити наявний тест назви**

У `tests/test_models/test_course.py` замінити тіло `test_course_event_type_label` (рядки 19-22) на:

```python
def test_course_event_type_label(db_session):
    """Назва береться з довідника, а не з константи моделі."""
    course = Course(title='C', slug='c-type', event_type='seminar')
    assert course.event_type_label == 'Семінар'


def test_course_event_type_label_of_unknown_code_is_the_code(db_session):
    course = Course(title='C', slug='c-type-x', event_type='no-such')
    assert course.event_type_label == 'no-such'
```

- [ ] **Step 7: Прогнати тести**

Run: `python -m pytest tests/test_models tests/test_services/test_event_types.py -v`
Expected: PASS

- [ ] **Step 8: Знайти решту споживачів константи**

Run: `grep -rn "EVENT_TYPES" --include=*.py app/ tests/ | grep -v notification`
Expected: залишаються лише оголошення в `app/models/course.py` і два його споживачі — `app/admin/forms.py` (Task 5) і `app/services/xlsx_io.py` (Task 7, там же константа й видаляється). Будь-що інше в цьому переліку — незапланований споживач: спинитись і сказати про нього, а не глушити.

- [ ] **Step 9: Коміт**

```bash
git add app/models/course.py app/models/course_instance.py app/courses/routes.py \
        tests/test_models/test_course.py tests/test_models/test_course_instance_event_type.py
git commit -m "feat(courses): назва виду заходу з довідника, перевизначення в проведенні"
```

---

### Task 4: Сторінка `/admin/event-types`

**Files:**
- Create: `app/admin/routes_event_types.py`
- Create: `app/templates/admin/event_types.html`
- Create: `app/static/css/page-admin-event-types.css`
- Create: `tests/test_routes/test_admin_event_types.py`
- Modify: `app/admin/routes.py:7`
- Modify: `app/rbac/registry.py:72`
- Modify: `app/templates/admin/partials/_sidebar.html:40`

**Interfaces:**
- Consumes: `event_types.usage`, `event_types.reset_cache`, `EventType`, `SEED_ROWS`.
- Produces: ендпоінти `admin.event_types_list`, `admin.event_types_save`, `admin.event_types_add`, `admin.event_types_delete`; права `event_types.view|manage|delete`.

- [ ] **Step 1: Написати тести адмінки**

Створити `tests/test_routes/test_admin_event_types.py`:

```python
"""Адмінка довідника видів заходів: доступ, збереження, додавання, видалення."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.event_type import EventType
from app.models.user import User
from app.services import event_types
from tests.support.rbac import grant_role


@pytest.fixture
def admin():
    u = User.create_with_password(
        f'et-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _custom(**kw):
    row = EventType(code=kw.pop('code', f'z-{uuid4().hex[:6]}'),
                    name=kw.pop('name', 'Тимчасовий тип'),
                    sort_order=kw.pop('sort_order', 500), **kw)
    db.session.add(row)
    db.session.flush()
    event_types.reset_cache()
    return row


def test_requires_admin(client):
    assert client.get('/admin/event-types').status_code in (302, 401, 403)


def test_list_shows_active_and_legacy_rows(client, admin):
    _login(client, admin)
    html = client.get('/admin/event-types').get_data(as_text=True)
    assert 'Наукова конференція' in html
    assert 'Фахова (тематична) школа' in html
    # Саме за кодом у комірці: рядок «Курс» є в хлібних крихтах («Курси»)
    # незалежно від таблиці, тож перевірка за назвою нічого не стерегла б.
    assert '<code>course</code>' in html, 'застарілий рядок теж мусить бути видимим'


def test_save_updates_names_cases_and_flags(client, admin):
    _login(client, admin)
    row = _custom(name='Стара назва', is_active=True)
    client.post('/admin/event-types/save', data={
        f'name__{row.id}': 'Нова назва',
        f'accusative__{row.id}': 'нову назву',
        f'genitive__{row.id}': 'нової назви',
        f'sort__{row.id}': '7',
        f'tr__en__{row.id}': 'New name',
    })
    db.session.expire(row)
    assert row.name == 'Нова назва'
    assert row.name_accusative == 'нову назву'
    assert row.name_genitive == 'нової назви'
    assert row.sort_order == 7
    assert row.t('name', 'en') == 'New name'
    assert row.is_active is False, 'галка не прийшла -- тип деактивовано'


def test_save_keeps_row_active_when_checkbox_present(client, admin):
    _login(client, admin)
    row = _custom(is_active=True)
    client.post('/admin/event-types/save', data={
        f'name__{row.id}': row.name,
        f'active__{row.id}': 'on',
    })
    db.session.expire(row)
    assert row.is_active is True


def test_save_ignores_blank_name(client, admin):
    _login(client, admin)
    row = _custom(name='Лишається')
    client.post('/admin/event-types/save', data={f'name__{row.id}': '   '})
    db.session.expire(row)
    assert row.name == 'Лишається'


def test_add_creates_row(client, admin):
    _login(client, admin)
    code = f'z-{uuid4().hex[:6]}'
    r = client.post('/admin/event-types/add', data={
        'code': code, 'name': 'Новий вид',
        'accusative': 'новий вид', 'genitive': 'нового виду',
    })
    assert r.status_code == 302
    row = EventType.query.filter_by(code=code).one()
    assert row.name == 'Новий вид'
    assert row.is_active is True


def test_add_rejects_duplicate_code(client, admin):
    _login(client, admin)
    before = EventType.query.count()
    client.post('/admin/event-types/add', data={'code': 'seminar', 'name': 'Дубль'})
    assert EventType.query.count() == before


def test_add_rejects_empty_code_or_name(client, admin):
    _login(client, admin)
    before = EventType.query.count()
    client.post('/admin/event-types/add', data={'code': '  ', 'name': 'Без коду'})
    client.post('/admin/event-types/add', data={'code': 'ok-code', 'name': '  '})
    assert EventType.query.count() == before


def test_delete_removes_unused_row(client, admin):
    _login(client, admin)
    row = _custom()
    code = row.code
    client.post(f'/admin/event-types/{row.id}/delete')
    assert EventType.query.filter_by(code=code).first() is None


def test_delete_is_blocked_for_row_in_use(client, admin):
    _login(client, admin)
    row = _custom()
    db.session.add(Course(title='К', slug=f'd-{uuid4().hex[:6]}', event_type=row.code))
    db.session.flush()

    client.post(f'/admin/event-types/{row.id}/delete')
    assert EventType.query.filter_by(code=row.code).first() is not None, (
        'вживаний тип видаляти не можна -- його деактивують'
    )
```

- [ ] **Step 2: Прогнати тести й переконатись, що вони падають**

Run: `python -m pytest tests/test_routes/test_admin_event_types.py -v`
Expected: FAIL — усі, крім `test_requires_admin`, бо маршруту ще немає (404).

- [ ] **Step 3: Додати модуль у реєстр прав**

У `app/rbac/registry.py`, одразу після `Module('cities', …)` (рядки 72-73), додати:

```python
    Module('event_types', 'Довідник типів заходів', 'content', _VMD,
           endpoint='admin.event_types_list'),
```

- [ ] **Step 4: Написати роути**

Створити `app/admin/routes_event_types.py`:

```python
"""Адмінка довідника видів заходів БПР.

Довідник плоский і на півтора десятка рядків, тож окремої сторінки
редагування немає: уся таблиця правиться і зберігається одним сабмітом --
той самий підхід, що в довіднику локацій.

Вживаний тип не видаляється, а деактивується. Інакше зміна номенклатури
лишила б курси з кодом, якого вже ніде немає, і вони показували б голий
латинський рядок замість назви.
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin._helpers import try_commit
from app.extensions import db
from app.i18n import PREFIXED_LANGUAGES
from app.models.event_type import EventType
from app.rbac import permission_required
from app.services import event_types

audit_logger = logging.getLogger('audit')


def _rows():
    """Рядок таблиці збираємо тут, а не в шаблоні: розкопувати JSON
    перекладів у Jinja -- логіка не на своєму поверсі."""
    usage = event_types.usage()
    rows = []
    for row in EventType.query.order_by(EventType.sort_order, EventType.name).all():
        stored = row.translations or {}
        # Ключ саме 'tr': row.values у Jinja дало б метод dict.values.
        rows.append({
            'type': row,
            'tr': {lang: ((stored.get(lang) or {}).get('name') or '')
                   for lang in PREFIXED_LANGUAGES},
            'uses': usage.get(row.code, 0),
        })
    return rows


@admin_bp.route('/event-types', methods=['GET'])
@permission_required('event_types.view')
def event_types_list():
    rows = _rows()
    return render_template(
        'admin/event_types.html',
        rows=rows,
        languages=PREFIXED_LANGUAGES,
        active_count=sum(1 for r in rows if r['type'].is_active),
    )


@admin_bp.route('/event-types/save', methods=['POST'])
@permission_required('event_types.manage')
def event_types_save():
    """Зберегти всю таблицю одним сабмітом."""
    changed = 0
    for row in EventType.query.all():
        name_key = f'name__{row.id}'
        if name_key not in request.form:
            continue
        name = (request.form.get(name_key) or '').strip()
        if name:
            row.name = name
        row.name_accusative = (request.form.get(f'accusative__{row.id}') or '').strip() or None
        row.name_genitive = (request.form.get(f'genitive__{row.id}') or '').strip() or None
        try:
            row.sort_order = int(request.form.get(f'sort__{row.id}') or row.sort_order)
        except ValueError:
            pass
        # Незнята галка чекбокса просто не приходить у form -- саме так
        # рядок і деактивують.
        row.is_active = f'active__{row.id}' in request.form
        for lang in PREFIXED_LANGUAGES:
            row.set_translation(
                lang, 'name',
                (request.form.get(f'tr__{lang}__{row.id}') or '').strip() or None,
            )
        changed += 1

    if try_commit(log_context='event_types_save'):
        event_types.reset_cache()
        audit_logger.info('Admin %s updated event type directory (%s rows)',
                          current_user.email, changed)
        flash('Довідник збережено.', 'success')
    return redirect(url_for('admin.event_types_list'))


@admin_bp.route('/event-types/add', methods=['POST'])
@permission_required('event_types.manage')
def event_types_add():
    code = (request.form.get('code') or '').strip().lower()
    name = (request.form.get('name') or '').strip()
    if not code or not name:
        flash('Вкажіть і код, і назву типу', 'error')
        return redirect(url_for('admin.event_types_list'))

    if EventType.query.filter_by(code=code).first():
        flash(f'Тип з кодом "{code}" уже є в довіднику', 'info')
        return redirect(url_for('admin.event_types_list'))

    last = db.session.query(db.func.max(EventType.sort_order)).scalar() or 0
    db.session.add(EventType(
        code=code,
        name=name,
        name_accusative=(request.form.get('accusative') or '').strip() or None,
        name_genitive=(request.form.get('genitive') or '').strip() or None,
        sort_order=last + 1,
        is_active=True,
    ))
    if try_commit(log_context=f'event_types_add code={code!r}',
                  error_msg='Не вдалося додати тип (можливо, його щойно '
                            'додав інший адміністратор)'):
        event_types.reset_cache()
        audit_logger.info('Admin %s added event type %r', current_user.email, code)
        flash(f'Додано "{name}". Впишіть відмінки й переклади та збережіть.', 'success')
    return redirect(url_for('admin.event_types_list'))


@admin_bp.route('/event-types/<int:type_id>/delete', methods=['POST'])
@permission_required('event_types.delete')
def event_types_delete(type_id):
    row = db.session.get(EventType, type_id)
    if row is None:
        flash('Тип не знайдено', 'error')
        return redirect(url_for('admin.event_types_list'))

    uses = event_types.usage().get(row.code, 0)
    if uses:
        flash(f'"{row.name}" вживається у {uses} курсах і проведеннях. '
              f'Зніміть галку «Активний» замість видалення.', 'error')
        return redirect(url_for('admin.event_types_list'))

    name = row.name
    db.session.delete(row)
    if try_commit(log_context=f'event_types_delete id={type_id}'):
        event_types.reset_cache()
        audit_logger.info('Admin %s deleted event type %r', current_user.email, name)
        flash(f'"{name}" видалено з довідника.', 'success')
    return redirect(url_for('admin.event_types_list'))
```

- [ ] **Step 5: Підключити модуль роутів**

У `app/admin/routes.py`, поруч із рядком 7, додати:

```python
from app.admin import routes_event_types  # noqa: F401
```

- [ ] **Step 6: Написати шаблон**

Створити `app/templates/admin/event_types.html`:

```html
{% extends "admin/base_admin.html" %}

{% block title %}Довідник типів заходів | ІПРМ{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/admin.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-admin-event-types.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="admin-with-sidebar">
  {% include 'admin/partials/_sidebar.html' %}
  <div class="admin-layout admin-layout--wide">

    <div class="admin-hero">
      <div>
        <div class="admin-breadcrumb">
          <a href="{{ url_for('admin.courses_list') }}" class="admin-breadcrumb__link">Курси</a>
          <span class="admin-breadcrumb__sep">/</span>
          <span class="admin-breadcrumb__current">Довідник типів заходів</span>
        </div>
        <h1 class="admin-hero__title">Довідник типів заходів</h1>
        <p class="admin-hero__subtitle">
          Номенклатура видів заходів БПР. Знята галка «Активний» прибирає тип із вибору,
          але курси, де він уже стоїть, показуються як раніше. Відмінки друкуються
          в сертифікатах, тому пишуться з малої літери.
        </p>
      </div>
    </div>

    {% include 'partials/flash_messages.html' %}

    <div class="admin-stat-cards admin-stat-cards--3">
      <div class="admin-stat-card">
        <span class="admin-stat-card__value">{{ active_count }}</span>
        <span class="admin-stat-card__label">Активних типів</span>
      </div>
      <div class="admin-stat-card">
        <span class="admin-stat-card__value">{{ rows | length - active_count }}</span>
        <span class="admin-stat-card__label">Застарілих</span>
      </div>
      <div class="admin-stat-card">
        <span class="admin-stat-card__value">{{ rows | length }}</span>
        <span class="admin-stat-card__label">Усього в довіднику</span>
      </div>
    </div>

    <div class="form-section">
      <h2 class="event-types-panel__title">Додати тип</h2>
      <p class="event-types-panel__hint">
        Код -- латиницею, він потрапляє в партнерське API та xlsx і надалі не змінюється.
      </p>
      <form method="POST" action="{{ url_for('admin.event_types_add') }}" class="event-types-add">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="text" name="code" class="form-input" maxlength="30"
               placeholder="workshop" aria-label="Код типу">
        <input type="text" name="name" class="form-input" maxlength="120"
               placeholder="Воркшоп" aria-label="Назва, називний відмінок">
        <input type="text" name="accusative" class="form-input" maxlength="120"
               placeholder="воркшоп" aria-label="Знахідний відмінок">
        <input type="text" name="genitive" class="form-input" maxlength="120"
               placeholder="воркшопу" aria-label="Родовий відмінок">
        <button type="submit" class="btn-admin btn-admin--secondary">{{ icon('add') }} Додати</button>
      </form>
    </div>

    <form method="POST" action="{{ url_for('admin.event_types_save') }}" class="admin-form">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <div class="admin-table-wrap">
        <table class="admin-table event-types-table">
          <thead>
            <tr>
              <th class="event-types-col-code">Код</th>
              <th>Назва</th>
              <th>Знахідний</th>
              <th>Родовий</th>
              {% for lang in languages %}<th>{{ 'Російська' if lang == 'ru' else 'Англійська' }}</th>{% endfor %}
              <th class="event-types-col-sort">Порядок</th>
              <th class="event-types-col-uses" title="Курсів і проведень цим типом">Вжито</th>
              <th class="event-types-col-status">Активний</th>
              <th class="event-types-col-actions">Дії</th>
            </tr>
          </thead>
          <tbody>
            {% for row in rows %}
            <tr>
              <td class="event-types-col-code"><code>{{ row.type.code }}</code></td>
              <td>
                <input type="text" class="form-input" maxlength="120"
                       name="name__{{ row.type.id }}" value="{{ row.type.name }}"
                       aria-label="Назва типу {{ row.type.code }}">
              </td>
              <td>
                <input type="text" class="form-input" maxlength="120"
                       name="accusative__{{ row.type.id }}"
                       value="{{ row.type.name_accusative or '' }}" placeholder="–"
                       aria-label="{{ row.type.name }} – знахідний відмінок">
              </td>
              <td>
                <input type="text" class="form-input" maxlength="120"
                       name="genitive__{{ row.type.id }}"
                       value="{{ row.type.name_genitive or '' }}" placeholder="–"
                       aria-label="{{ row.type.name }} – родовий відмінок">
              </td>
              {% for lang in languages %}
              <td>
                <input type="text" class="form-input" maxlength="120"
                       name="tr__{{ lang }}__{{ row.type.id }}" value="{{ row.tr[lang] }}"
                       placeholder="–"
                       aria-label="{{ row.type.name }} – {{ 'російська' if lang == 'ru' else 'англійська' }}">
              </td>
              {% endfor %}
              <td class="event-types-col-sort">
                <input type="number" class="form-input" name="sort__{{ row.type.id }}"
                       value="{{ row.type.sort_order }}"
                       aria-label="Порядок типу {{ row.type.name }}">
              </td>
              <td class="event-types-col-uses">
                {% if row.uses %}
                  <a href="{{ url_for('admin.courses_list') }}">{{ row.uses }}</a>
                {% else %}
                  <span class="admin-text-muted" title="Тип ніде не вживається">–</span>
                {% endif %}
              </td>
              <td class="event-types-col-status">
                <input type="checkbox" name="active__{{ row.type.id }}"
                       id="active__{{ row.type.id }}"
                       {% if row.type.is_active %}checked{% endif %}>
                <label for="active__{{ row.type.id }}" class="visually-hidden">
                  Активний: {{ row.type.name }}
                </label>
              </td>
              <td class="event-types-col-actions">
                {# Форма видалення живе поза формою збереження (вкладені form
                   невалідні); кнопка прив'язана до неї атрибутом form. #}
                <button type="submit" form="event-type-delete-{{ row.type.id }}"
                        class="btn-admin btn-admin--danger btn-admin--sm btn-admin--icon"
                        {% if row.uses %}disabled title="Тип вживається -- зніміть галку «Активний»"{% endif %}>
                  {{ icon('delete', label='Видалити') }}
                </button>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      <div class="admin-form__actions">
        <button type="submit" class="btn-admin btn-admin--primary">Зберегти довідник</button>
      </div>
    </form>

    {% for row in rows %}
    <form method="POST" id="event-type-delete-{{ row.type.id }}"
          action="{{ url_for('admin.event_types_delete', type_id=row.type.id) }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    </form>
    {% endfor %}

  </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Написати сторінковий CSS (лише layout)**

Створити `app/static/css/page-admin-event-types.css`:

```css
/* Довідник типів заходів -- лише сітка й ширини колонок.
   Декор (кнопки, поля, бейджі, таблиця) береться з admin.css. */

.event-types-add {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.event-types-add .form-input {
  flex: 1 1 160px;
  min-width: 0;
}

.event-types-table .event-types-col-code { width: 168px; }
.event-types-table .event-types-col-sort { width: 88px; }
.event-types-table .event-types-col-uses { width: 72px; text-align: center; }
.event-types-table .event-types-col-status { width: 88px; text-align: center; }
.event-types-table .event-types-col-actions { width: 72px; text-align: right; }
```

Значення в px, а не в токенах: сусідній `page-admin-cities.css` теж пише
ширини колонок числами, і власного набору токенів під це в `common.css`
немає — вводити його заради однієї таблиці не варто.

- [ ] **Step 8: Додати пункт сайдбару**

У `app/templates/admin/partials/_sidebar.html`, одразу після блоку `cities` (рядки 40-45), додати:

```html
      {% if can('event_types.view') %}
      <a href="{{ url_for('admin.event_types_list') }}" class="admin-sidebar__link admin-sidebar__link--sub{% if ep in ('admin.event_types_list', 'admin.event_types_save', 'admin.event_types_add', 'admin.event_types_delete') %} admin-sidebar__link--active{% endif %}">
        {{ icon('table_view') }}
        <span class="admin-sidebar__text">Довідник типів заходів</span>
      </a>
      {% endif %}
```

Іконка `table_view` — та сама, що в довідника локацій; у реєстрі
`app/icons.py:91` вона вже є, а `category` там немає, і додавання нового
гліфа тягло б за собою правку шрифтового підмножини.

- [ ] **Step 9: Синхронізувати права в dev-БД**

Run: `python -m flask rbac sync`
Expected: у виводі згадані нові права `event_types.view`, `event_types.manage`, `event_types.delete`

- [ ] **Step 10: Прогнати тести адмінки й вартових RBAC**

Run: `python -m pytest tests/test_routes/test_admin_event_types.py tests/test_rbac -v`
Expected: PASS. `test_sidebar.py::test_every_sidebar_link_is_gated` перевіряє, що пункт стоїть за правом входу модуля — якщо він упав, гейт не збігається з `entry_permission`.

- [ ] **Step 11: Прогнати вартових дизайн-системи**

Run: `python -m pytest tests/test_design_system -q`
Then: `python tools/ds/ds_audit.py`
Expected: PASS; жоден клас із `page-admin-event-types.css` не дублює оголошення в `admin.css` чи `common.css`.

- [ ] **Step 12: Коміт**

```bash
git add app/admin/routes_event_types.py app/admin/routes.py app/rbac/registry.py \
        app/templates/admin/event_types.html app/templates/admin/partials/_sidebar.html \
        app/static/css/page-admin-event-types.css tests/test_routes/test_admin_event_types.py
git commit -m "feat(admin): сторінка довідника типів заходів"
```

---

### Task 5: Форми курсу і проведення

**Files:**
- Modify: `app/admin/forms.py:464-468`
- Modify: `app/admin/forms.py` (форма проведення, поруч із рядком 719)
- Modify: `app/admin/routes_courses.py:87,130`
- Modify: `app/admin/routes_instances.py`
- Modify: `app/admin/_helpers.py` (спільний хелпер)
- Modify: `app/templates/admin/instance_edit.html`
- Create: `tests/test_routes/test_admin_course_event_type_choices.py`

**Interfaces:**
- Consumes: `event_types.choices` з Task 2.
- Produces: `_helpers.populate_event_type_choices(form, current=None) -> None` — заповнює `form.event_type.choices`.

- [ ] **Step 1: Написати тест на пастку з деактивованим типом**

Створити `tests/test_routes/test_admin_course_event_type_choices.py`:

```python
"""Вибір типу в адмінці курсу: активні + чинний, навіть застарілий.

Головна регресія тут -- курс зі старим типом («Курс», «Вебінар»).
Якщо його значення не потрапляє в choices, WTForms валить сабміт із
"Not a valid choice", і адміністратор не збереже навіть правку
заголовка, що типу взагалі не стосується.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.user import User
from tests.support.rbac import grant_role


@pytest.fixture
def admin():
    u = User.create_with_password(
        f'ch-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _course(event_type):
    course = Course(title='Курс', slug=f'ch-{uuid4().hex[:6]}',
                    is_active=True, event_type=event_type)
    db.session.add(course)
    db.session.flush()
    return course


def test_new_course_form_offers_only_active_types(client, admin):
    _login(client, admin)
    html = client.get('/admin/courses/new').get_data(as_text=True)
    assert 'value="scientific_conference"' in html
    assert 'value="professional_school"' in html
    assert 'value="webinar"' not in html, 'застарілий тип не пропонується'


def test_edit_form_keeps_deactivated_current_type(client, admin):
    _login(client, admin)
    course = _course('course')
    html = client.get(f'/admin/courses/{course.id}/edit').get_data(as_text=True)
    assert 'value="course"' in html
    assert 'застарілий' in html


def test_saving_course_with_deactivated_type_succeeds(client, admin):
    """Правка заголовка не мусить впиратись у застарілий тип."""
    _login(client, admin)
    course = _course('webinar')
    r = client.post(f'/admin/courses/{course.id}/edit', data={
        'title': 'Оновлений заголовок',
        'slug': course.slug,
        'event_type': 'webinar',
        'difficulty_level': '0',
        'base_price': '0',
    }, follow_redirects=True)

    assert r.status_code == 200
    db.session.expire(course)
    assert course.title == 'Оновлений заголовок'
    assert course.event_type == 'webinar'


def test_course_can_be_switched_to_new_bpr_type(client, admin):
    _login(client, admin)
    course = _course('course')
    client.post(f'/admin/courses/{course.id}/edit', data={
        'title': course.title,
        'slug': course.slug,
        'event_type': 'skills_training',
        'difficulty_level': '0',
        'base_price': '0',
    }, follow_redirects=True)

    db.session.expire(course)
    assert course.event_type == 'skills_training'
```

- [ ] **Step 2: Прогнати тести й переконатись, що вони падають**

Run: `python -m pytest tests/test_routes/test_admin_course_event_type_choices.py -v`
Expected: FAIL — форма ще віддає статичні п'ять типів зі старої константи, тож `value="scientific_conference"` у HTML немає, а `value="webinar"` є.

- [ ] **Step 3: Прибрати статичні choices із форми курсу**

У `app/admin/forms.py` замінити поле (рядки 464-468) на:

```python
    event_type = SelectField(
        'Тип',
        # choices не можна рахувати тут: перелік живе в БД, а тіло класу
        # виконується на імпорті модуля, коли контексту застосунку ще
        # немає. Заповнюється в роуті через populate_event_type_choices.
        choices=[],
        validators=[DataRequired()],
        description='Вид заходу за номенклатурою БПР. Перелік редагується '
                    'у «Довідник типів заходів».',
    )
```

Прибрати `from app.models.course import Course`, якщо після цього він у файлі більше не потрібен; якщо потрібен для інших полів — лишити.

- [ ] **Step 4: Додати поле у форму проведення**

У `app/admin/forms.py`, у `CourseInstanceForm`, одразу після `event_format` (рядок 719-722), додати:

```python
    event_type = SelectField(
        'Вид заходу',
        choices=[],
        validators=[Optional()],
        description='Порожньо -- береться вид заходу курсу.',
    )
```

- [ ] **Step 5: Написати спільний хелпер**

У `app/admin/_helpers.py`, поруч із `populate_trainer_choices` (рядок 363), додати:

```python
def populate_event_type_choices(form, current=None, empty_label=None):
    """Заповнити form.event_type.choices з довідника.

    `current` -- код, що вже стоїть у сутності. Він домішується, навіть
    коли тип деактивовано: інакше WTForms відхилив би сабміт старої
    сутності з "Not a valid choice".
    """
    from app.services import event_types
    choices = event_types.choices(current=current)
    if empty_label is not None:
        choices = [('', empty_label)] + choices
    form.event_type.choices = choices
```

- [ ] **Step 6: Заповнити choices у роутах курсу**

У `app/admin/routes_courses.py` у `course_create` (рядок 88), одразу після `populate_trainer_choices(form)`:

```python
    populate_event_type_choices(form)
```

У `course_edit` (рядок 131), одразу після `populate_trainer_choices(form)`:

```python
    populate_event_type_choices(form, current=course.event_type)
```

Додати `populate_event_type_choices` в наявний імпорт з `app.admin._helpers`.

- [ ] **Step 7: Заповнити choices у роутах проведення**

Обидва роути проведення ходять через спільний `_populate_choices` (рядок 33), і чинного типу він не знає — тож додаємо йому параметр.

Змінити сигнатуру на рядку 33:

```python
def _populate_choices(form, preselected_course_id=None, current_event_type=None):
```

і в кінець тіла функції, після блоку `form.city_id.choices` (рядок 48-50), додати:

```python
    populate_event_type_choices(
        form, current=current_event_type, empty_label='– Як у курсу –',
    )
```

Додати `populate_event_type_choices` в наявний імпорт з `app.admin._helpers` (там уже береться `populate_trainer_choices`).

Оновити обидва виклики. У `instance_create` (рядок 289) лишається як є — нова сутність чинного типу не має:

```python
    _populate_choices(form, preselected)
```

У `instance_edit` (рядок 324) передати тип редагованого проведення:

```python
    _populate_choices(form, current_event_type=instance.event_type)
```

- [ ] **Step 8: Показати поле в шаблоні проведення**

У `app/templates/admin/instance_edit.html`, одразу після блоку `event_format` (рядки 86-89), додати:

```html
        <div class="form-group">
          <label for="event_type">Вид заходу</label>
          {{ form.event_type(class="form-input", id="event_type") }}
          <small class="form-hint">{{ form.event_type.description }}</small>
        </div>
```

`form-group`, `form-input` і `<small class="form-hint">` — рівно ті класи,
що вже вжиті сусідніми полями в цьому файлі (`event_format` на рядку 87,
`location.description` на рядку 99). Зірочки обов'язковості немає: поле
необов'язкове.

- [ ] **Step 9: Прогнати тести**

Run: `python -m pytest tests/test_routes/test_admin_course_event_type_choices.py -v`
Expected: PASS (4 тести)

- [ ] **Step 10: Прогнати всі маршрути адмінки**

Run: `python -m pytest tests/test_routes -q`
Expected: PASS. Тести, що постять форму курсу з `'event_type': 'course'` (наприклад `test_admin_landing_fields.py:53`, `test_admin_inline_translations.py:50`), мусять проходити без правок — саме заради цього застарілі коди лишилися в довіднику.

- [ ] **Step 11: Коміт**

```bash
git add app/admin/forms.py app/admin/_helpers.py app/admin/routes_courses.py \
        app/admin/routes_instances.py app/templates/admin/instance_edit.html \
        tests/test_routes/test_admin_course_event_type_choices.py
git commit -m "feat(admin): вибір виду заходу з довідника, перевизначення в проведенні"
```

---

### Task 6: Сертифікати — відмінки з довідника

**Files:**
- Modify: `app/services/certificate_service.py:197`
- Modify: `app/services/certificate_service.py:369-388`
- Modify: `app/services/certificate_service.py:726`
- Create: `tests/test_services/test_certificate_event_type_cases.py`

**Interfaces:**
- Consumes: `event_types.accusative`, `event_types.genitive`, `CourseInstance.effective_event_type`.
- Produces: `_EVENT_TYPE_GENITIVE` і `event_type_genitive()` більше не існують.

- [ ] **Step 1: Написати тести відмінків**

Створити `tests/test_services/test_certificate_event_type_cases.py`:

```python
"""Відмінки виду заходу в сертифікатах.

Учасницький друкує "успішно завершив(-ла) <знахідний>", лекторський --
"лектору(-ці) <родовий>". До довідника знахідний брався як називний у
нижньому регістрі, через що жіночі назви давали "завершив(-ла)
конференція". Ці тести пінять правильні форми.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.services import certificate_service


def _instance(course_type='scientific_conference', instance_type=None):
    course = Course(title='К', slug=f'ce-{uuid4().hex[:6]}',
                    is_active=True, event_type=course_type)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, event_type=instance_type,
        start_date=datetime.now(timezone.utc) - timedelta(days=1),
        status='published',
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def test_participant_case_is_accusative_for_feminine_type(db_session):
    inst = _instance('scientific_conference')
    assert certificate_service.event_type_accusative_for(inst) == 'наукову конференцію'


def test_participant_case_for_masculine_type(db_session):
    inst = _instance('training')
    assert certificate_service.event_type_accusative_for(inst) == 'тренінг'


def test_lecturer_case_is_genitive(db_session):
    inst = _instance('professional_school')
    assert certificate_service.event_type_genitive_for(inst) == 'фахової (тематичної) школи'


def test_instance_override_wins_over_course_type(db_session):
    inst = _instance('seminar', instance_type='congress')
    assert certificate_service.event_type_accusative_for(inst) == 'конгрес'
    assert certificate_service.event_type_genitive_for(inst) == 'конгресу'


def test_no_type_yields_none_so_template_prints_default(db_session):
    inst = _instance(None)
    assert certificate_service.event_type_accusative_for(inst) is None
    assert certificate_service.event_type_genitive_for(inst) is None


def test_hardcoded_genitive_map_is_gone():
    assert not hasattr(certificate_service, '_EVENT_TYPE_GENITIVE'), (
        'відмінки живуть у довіднику, а не в мапі всередині служби'
    )
```

- [ ] **Step 2: Прогнати тести й переконатись, що вони падають**

Run: `python -m pytest tests/test_services/test_certificate_event_type_cases.py -v`
Expected: FAIL, `AttributeError: module has no attribute 'event_type_accusative_for'`

- [ ] **Step 3: Замінити мапу відмінків на довідник**

У `app/services/certificate_service.py` видалити `_EVENT_TYPE_GENITIVE` (рядки 369-380) і `event_type_genitive` (рядки 383-388), а замість них додати:

```python
def event_type_accusative_for(instance):
    """Знахідний виду заходу проведення: "завершив(-ла) наукову конференцію".

    Береться ефективний тип -- власний тип проведення, а якщо його немає,
    тип курсу.
    """
    from app.services import event_types
    return event_types.accusative(instance.effective_event_type) if instance else None


def event_type_genitive_for(instance):
    """Родовий виду заходу проведення: "лектору(-ці) наукової конференції"."""
    from app.services import event_types
    return event_types.genitive(instance.effective_event_type) if instance else None
```

- [ ] **Step 4: Перевести учасницький сертифікат на знахідний**

У `_event_snapshot` замінити рядок 197:

```python
    event_type = event_type_accusative_for(instance)
```

Рядок був `course.event_type_label.lower() if course and course.event_type else None` -- саме він і давав «завершив(-ла) конференція».

- [ ] **Step 5: Перевести лекторський сертифікат на новий хелпер**

Замінити рядок 726:

```python
    event_type = event_type_genitive_for(instance)
```

- [ ] **Step 6: Перевірити, що старий хелпер ніде не лишився**

Run: `grep -rn "event_type_genitive\b" --include=*.py app/ tests/`
Expected: жодного збігу поза `event_type_genitive_for`

- [ ] **Step 7: Прогнати тести**

Run: `python -m pytest tests/test_services/test_certificate_event_type_cases.py -v`
Expected: PASS (6 тестів)

- [ ] **Step 8: Прогнати всі тести сертифікатів**

Run: `python -m pytest tests/test_services -q -k "certificate or cert"`
Expected: PASS

- [ ] **Step 9: Коміт**

```bash
git add app/services/certificate_service.py tests/test_services/test_certificate_event_type_cases.py
git commit -m "fix(certificates): відмінки виду заходу з довідника, знахідний замість називного"
```

---

### Task 7: XLSX — валідація і drop-down з довідника

**Files:**
- Modify: `app/services/xlsx_io.py:227-232`
- Modify: `app/services/xlsx_io.py:795-801`
- Modify: `app/services/xlsx_io.py:918-927`
- Create: `tests/test_services/test_xlsx_event_types.py`

**Interfaces:**
- Consumes: `event_types.directory`, `event_types.choices`.
- Produces: `xlsx_io.normalize_event_type(raw) -> str` — приймає код або українську назву, віддає код; кидає `ValueError` на невідомому.

- [ ] **Step 1: Написати тести імпорту**

Створити `tests/test_services/test_xlsx_event_types.py`:

```python
"""Нормалізація виду заходу при xlsx-імпорті.

Файл може прийти і з внутрішнім кодом ('seminar'), і з українською
назвою з drop-down ('Семінар'). Старі вигрузки несуть застарілі типи --
вони мусять заходити далі, інакше архівні файли перестануть імпортуватись.
"""
import pytest

from app.services import xlsx_io


def test_accepts_internal_code(app):
    assert xlsx_io.normalize_event_type('seminar') == 'seminar'


def test_accepts_ukrainian_label(app):
    assert xlsx_io.normalize_event_type('Наукова конференція') == 'scientific_conference'


def test_accepts_label_with_padding(app):
    assert xlsx_io.normalize_event_type('  Тренінг  ') == 'training'


def test_accepts_deactivated_legacy_type(app):
    assert xlsx_io.normalize_event_type('Курс') == 'course'
    assert xlsx_io.normalize_event_type('webinar') == 'webinar'


def test_rejects_unknown_type_with_helpful_message(app):
    with pytest.raises(ValueError) as err:
        xlsx_io.normalize_event_type('Вечірка')
    assert 'Вечірка' in str(err.value)


def test_dropdown_offers_only_active_types(app):
    options = xlsx_io.event_type_dropdown_options()
    assert 'Наукова конференція' in options
    assert 'Вебінар' not in options, 'застарілий тип не пропонується у новому файлі'
```

- [ ] **Step 2: Прогнати тести й переконатись, що вони падають**

Run: `python -m pytest tests/test_services/test_xlsx_event_types.py -v`
Expected: FAIL, `AttributeError: module 'app.services.xlsx_io' has no attribute 'normalize_event_type'`

- [ ] **Step 3: Замінити константи на функції**

У `app/services/xlsx_io.py` видалити рядки 227 і 231-233:

```python
VALID_EVENT_TYPES = {t[0] for t in Course.EVENT_TYPES}
EVENT_TYPE_LABEL = dict(Course.EVENT_TYPES)
EVENT_TYPE_KEY_BY_LABEL = {v: k for k, v in EVENT_TYPE_LABEL.items()}
```

Замість них додати (константи не можна лишати: тіло модуля виконується на імпорті, коли БД ще недосяжна):

```python
def event_type_dropdown_options():
    """Назви активних типів для drop-down у згенерованому файлі."""
    from app.services import event_types
    return [name for _code, name in event_types.choices()]


def normalize_event_type(raw):
    """Код виду заходу з того, що написали у клітинці.

    Приймає і внутрішній код ('seminar'), і українську назву з drop-down
    ('Семінар'), і застарілий тип: старі вигрузки мусять заходити далі.
    """
    from app.services import event_types

    value = (raw or '').strip()
    if not value:
        return None

    rows = event_types.directory()
    if value in rows:
        return value

    by_label = {row.name: code for code, row in rows.items()}
    if value in by_label:
        return by_label[value]

    allowed = sorted(rows) + sorted(by_label)
    raise ValueError(f'event_type={value!r} – допустимі: {allowed}')
```

- [ ] **Step 4: Підключити drop-down**

Замінити виклик на рядках 795-801:

```python
    # Drop-down для типу заходу.
    _add_inline_dropdown(
        ws, 'event_type', COURSE_COLS,
        options=event_type_dropdown_options(),
        last_data_row=courses_last_row,
        title='Тип заходу',
        hint='Оберіть зі списку: ' + ', '.join(event_type_dropdown_options()),
```

Захардкоджений рядок `'Оберіть зі списку: Семінар, Вебінар, Курс, Майстер-клас, Конференція'` видаляється — він розійшовся б із довідником на першій же зміні номенклатури.

- [ ] **Step 5: Підключити нормалізацію в імпорті**

Замінити рядки 918-927:

```python
            event_type = normalize_event_type(raw.get('event_type')) or 'seminar'
```

Дефолт змінюється з `'course'` на `'seminar'`: `course` тепер застарілий, і рядок без типу не має отримувати тип поза номенклатурою. Блок `if event_type not in VALID_EVENT_TYPES: raise ...` видаляється — перевірку робить `normalize_event_type`.

- [ ] **Step 5a: Прибрати константу з моделі курсу**

Це був останній її споживач. У `app/models/course.py` видалити блок `EVENT_TYPES` (рядки 173-179) цілком. Якщо в цьому ж файлі лишився імпорт, потрібний лише йому, — прибрати і його.

Перевірити, що споживачів справді не лишилось:

Run: `grep -rn "EVENT_TYPES" --include=*.py app/ tests/ | grep -v notification`
Expected: жодного збігу. Якщо щось знайшлось — спинитись і сказати про це, бо Task 3 і Task 5 мали залишити рівно двох споживачів.

- [ ] **Step 6: Прогнати тести**

Run: `python -m pytest tests/test_services/test_xlsx_event_types.py -v`
Expected: PASS (6 тестів)

- [ ] **Step 7: Прогнати всі тести xlsx**

Run: `python -m pytest tests -q -k xlsx`
Expected: PASS

- [ ] **Step 8: Коміт**

```bash
git add app/services/xlsx_io.py tests/test_services/test_xlsx_event_types.py
git commit -m "feat(xlsx): види заходів у імпорті й drop-down беруться з довідника"
```

---

### Task 8: Наскрізна перевірка й документація

**Files:**
- Modify: `README.md`
- Modify: `docs/models.md`

- [ ] **Step 1: Прогнати весь набір тестів**

Run: `python -m pytest -q`
Expected: PASS. Падіння тут — це реальний споживач, якого план не побачив; спинитись і сказати про нього, а не підганяти тест.

- [ ] **Step 2: Перевірити, що константа зникла остаточно**

Run: `grep -rn "Course.EVENT_TYPES\|EVENT_TYPE_KEY_BY_LABEL\|VALID_EVENT_TYPES" --include=*.py app/ tests/`
Expected: жодного збігу

- [ ] **Step 3: Перевірити сторінку очима**

Підняти застосунок і відкрити `/admin/event-types`, `/admin/courses/<id>/edit`, `/admin/instances/<id>/edit` і публічну `/courses`. Перевірити за `docs/superpowers/specs`-процедурою з пам'яті проєкту: дамп через тестовий клієнт + headless Chrome (`reference_visual_check`). Дивитись на три речі: таблиця довідника не дає горизонтального скролу, у виборі курсу 12 типів, бейдж на картці лишився на місці.

- [ ] **Step 4: Оновити README**

У розділ навігації README.md додати рядок про довідник видів заходів: де сторінка (`/admin/event-types`), що код курсу лишається рядком, що застарілі типи деактивовані, а не видалені, і що відмінки звідти друкуються в сертифікатах.

- [ ] **Step 5: Оновити docs/models.md**

Додати `EventType` у перелік моделей: призначення, ключ `code`, зв'язок «за кодом, без FK» з `Course.event_type` і `CourseInstance.event_type`.

- [ ] **Step 6: Коміт**

```bash
git add README.md docs/models.md
git commit -m "docs: довідник видів заходів БПР"
```

---

## Після реалізації: кроки на проді

Не частина коду, але без них фіча на проді не працює. Перелік продубльовано зі спеки:

1. `flask db upgrade` — застосувати `bpr_event_types_20260909`.
2. `flask rbac sync` — інакше права `event_types.*` не з'являться в матриці.
3. Роздати `event_types.view|manage|delete` потрібним ролям у `/admin/access`.
4. Звірити з mm-medic, чи приймає партнер нові коди в полі `event_type` (`congress`, `convention`, `scientific_conference`, …). Це поза цим репозиторієм.
5. Проставити нові типи наявним курсам: застарілі коди працюють, але для звітності БПР їх треба замінити свідомо.
