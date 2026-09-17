# Реєстрації, згруповані за заходами -- план впровадження

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дати на `/admin/registrations` режим «За заходами»: курс -> дата
проведення -> зареєстровані, з підсумками в заголовках і лінивим
довантаженням рядків учасників.

**Architecture:** Режим -- звичайний фільтр `view` на наявному маршруті, тому
фільтри, пресети, права й експорт лишаються одні. Сторінка складається лише з
чисел (два агрегувальні запити плюс гідратація проведень), а рядки учасників
приїжджають окремим маршрутом-фрагментом у момент розгортання дати. Рядок
учасника оголошується один раз як Jinja-макрос і вживається і плаcким списком,
і фрагментом.

**Tech Stack:** Flask + Jinja2, SQLAlchemy 2 / Flask-SQLAlchemy 3.1, pytest
(SQLite у тестах), vanilla JS без збірок, CSS дизайн-системи проєкту.

**Spec:** [docs/superpowers/specs/2026-09-17-registrations-grouped-by-event-design.md](../specs/2026-09-17-registrations-grouped-by-event-design.md)

## Global Constraints

- Гілка одна -- `main`. Ворктрі й фіча-гілок не заводити.
- Кожна задача = окремий коміт, українською, без згадок про інструмент.
  Файли перелічуються ЯВНО; `git add -A` і `git add .` заборонені.
- Пуш -- ніколи без прямого запиту.
- Задача, чиї тести червоні, не комітиться.
- Жодного інлайнового CSS/JS: стилі -- у файлі CSS, скрипти -- у файлі JS,
  підключення через `url_for('static', ...)` з `?v={{ assets_version }}`.
- Емодзі в коді немає.
- Компонент оголошується РІВНО в одному CSS-файлі. `admin-disclosure` живе в
  `app/static/css/admin.css` і мусить бути показаний у каталозі
  `/admin/design-system`, інакше падає
  `tests/test_design_system/test_catalog_coverage.py`.
- `page-admin-registrations.css` -- лише layout (сітка, ширини, відступи).
  Кольору, шрифта, межі й тіні в ньому бути не повинно, і його класи не
  сміють повторювати класи з `admin.css`
  (`tests/test_design_system/test_component_ownership.py`).
- Тести ходять по SQLite: жодного `FILTER (WHERE ...)`, тільки
  `func.count(case(...))` / `func.sum(case(...))`.
- Фікстури тестів створюють дані через `db.session.flush()` і НЕ комітять:
  автоматична фікстура `db_session` відкочує транзакцію. Закомічений
  користувач переживає тест і ламає `tests/test_routes/test_api_v1_clients.py`.
- Шаблон не сміє звати проведення назвою курсу: `inst.course.title`
  ловить `tests/test_lint_templates.py`. Для проведення -- `effective_title`.
- Права: і сторінка, і фрагмент -- під `@permission_required('registrations.view')`.
- Python у прогонах -- `venv/Scripts/python.exe` (Windows).

## Порядок задач

Задачі йдуть так, щоб зеленою була не лише кожна задача, а й дерево після
КОЖНОГО коміту: спільний рядок (1), числа (2), маршрут-фрагмент разом із його
layout-файлом (3), компонент у дизайн-системі з показом у каталозі (4), і лише
тоді сторінка, яка все це вживає (5), скрипт розгортання (6) і документація (7).

Дві залежності тут не косметичні, а технічні. Сторінка не може йти раніше за
маршрут-фрагмент: `url_for('admin.registration_group_rows', ...)` упав би
`BuildError`. І компонент не може йти після сторінки: `test_block_is_on_showcase`
параметризований по всіх класах-блоках `admin.css`, а
`test_every_class_in_markup_has_a_rule` -- по всій розмітці, тож клас без
правила або без вітрини робить збірку червоною в той самий коміт, де зʼявився.

---

### Task 1: Рядок учасника як макрос

Зараз `<tr>` списку реєстрацій лежить інлайном у `registrations.html`. Фрагмент
із Task 3 має вживати ТОЙ САМИЙ рядок, інакше дві таблиці розійдуться на першій
новій колонці. Ця задача -- чистий рефактор: поведінка й розмітка не змінюються.

**Files:**
- Create: `app/templates/admin/partials/_registration_row.html`
- Modify: `app/templates/admin/registrations.html:137-243`
- Modify: `app/admin/routes_registrations.py` (два нові хелпери, звужений
  `registrations_all`)

**Interfaces:**
- Produces: `_registration_row.html` з двома макросами --
  `registration_headers()` і `registration_row(reg, ctx, back_url='')`.
- Produces: `routes_registrations._registration_row_options()` -> `tuple`
  loader-опцій SQLAlchemy.
- Produces: `routes_registrations._registration_rows_context(rows)` ->
  `SimpleNamespace(referrer_map, quiz_states, quiz_statuses, surcharge_due)`.

- [ ] **Step 1: Зняти знімок HTML до правки**

Run: `venv/Scripts/python.exe tools/ds/html_snapshot.py capture --label before`
Це доказ, що перенос розмітки в макрос нічого не зрушив. Знімок сам по собі
слабкий там, де в тестовій базі немає рядків, тому справжнім сторожем лишається
Step 6 -- але дешевий доказ беремо теж.

- [ ] **Step 2: Створити партіал і перенести в нього розмітку**

Витягти два шматки чинного шаблону (перенос вирізанням, не переписуванням):

```bash
sed -n '140,150p' app/templates/admin/registrations.html   # <th> шапки, без <tr>
sed -n '155,241p' app/templates/admin/registrations.html   # рядок разом із <tr>
```

Створити `app/templates/admin/partials/_registration_row.html` такої будови:

```jinja
{# Рядок учасника в реєстрі реєстрацій -- ОДНЕ оголошення на два місця:
   плаский список (`registrations.html`) і фрагмент розгорнутого заходу
   (`_registration_rows.html`). Поки розмітка була скопійована, дві таблиці
   встигали розійтись на кожній новій колонці.

   ctx -- набір батчів на сторінку (`_registration_rows_context`): реферери,
   стан тестування, незакриті доплати. Одним обʼєктом, а не чотирма
   аргументами: показників у рядку більшатиме, а сигнатура макроса -- ні.

   back_url -- куди повернутись після дії в рядку. #}
{% from 'partials/_money.html' import money %}
{% from 'admin/partials/_registration_actions.html' import registration_actions %}
{% import 'admin/partials/_registration_progress.html' as progress %}

{% macro registration_headers() %}
{{ /* сюди вставити вивід sed -n '140,150p' -- без змін */ }}
{% endmacro %}

{% macro registration_row(reg, ctx, back_url='') %}
{{ /* сюди вставити вивід sed -n '155,241p' -- разом із <tr> і </tr> */ }}
{% endmacro %}
```

(Рядки-плейсхолдери з `/* ... */` у файлі не лишаються -- на їх місце стає
вирізаний текст.)

У перенесеному тексті змінюються рівно три звертання:

| Було | Стало |
|---|---|
| `referrer_map.get(reg.referral_code)` | `ctx.referrer_map.get(reg.referral_code)` |
| `surcharge_due.get(reg.id)` | `ctx.surcharge_due.get(reg.id)` |
| `progress.cells(reg, quiz_states, quiz_statuses)` | `progress.cells(reg, ctx.quiz_states, ctx.quiz_statuses)` |

`{{ registration_actions(reg, back_url) }}` лишається як є: `back_url` тепер
аргумент макроса. `{% from %}` / `{% import %}` на верхівці партіала видно
всередині його макросів -- перевірено, передавати їх окремо не треба.

- [ ] **Step 3: Перевести плаский список на макрос**

У `app/templates/admin/registrations.html`:

1. Прибрати імпорти, що переїхали: `registration_actions` і `progress`.
   `money` лишити, якщо він ще вживається вище (`grep -n "money(" app/templates/admin/registrations.html`).
2. Додати `{% from 'admin/partials/_registration_row.html' import registration_headers, registration_row %}`.
3. Замінити тіло таблиці на:

```jinja
    <table class="admin-table admin-table--wide">
      <thead>
        <tr>
          {{ registration_headers() }}
        </tr>
      </thead>
      <tbody>
        {% for reg in registrations %}
        {{ registration_row(reg, ctx, back_url) }}
        {% endfor %}
      </tbody>
    </table>
```

- [ ] **Step 4: Винести хелпери в роут**

У `app/admin/routes_registrations.py` додати `from types import SimpleNamespace`
у верхівку файлу і два хелпери поруч із `_registration_filters`:

```python
def _registration_row_options():
    """Loader-опції, без яких рядок учасника вистрілює запитом на колонку.

    medical_profile і quiz_attempts -- для колонок прогресу
    (_registration_progress.html). Учасники в реєстрі різні, тож без
    eager-load кожен рядок тягнув би анкету й спроби окремо.
    """
    return (
        joinedload(EventRegistration.user).joinedload(User.medical_profile),
        joinedload(EventRegistration.quiz_attempts),
        joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
        joinedload(EventRegistration.certificate),
        joinedload(EventRegistration.promo_code),
    )


def _registration_rows_context(rows):
    """Батчі, на яких стоїть рядок учасника -- один набір на сторінку.

    Спільне для плаского списку і для фрагмента розгорнутого заходу: поштучні
    виклики тут дають +5 SELECT на рядок, і саме це стереже
    test_page_does_not_grow_with_participants.
    """
    from app.services import quiz_service, referral_service, transfer_service
    return SimpleNamespace(
        referrer_map=referral_service.resolve_referrers_bulk(
            [r.referral_code for r in rows]),
        quiz_states=quiz_service.eligibility_map(rows),
        quiz_statuses=quiz_service,
        surcharge_due=transfer_service.unpaid_surcharge_amounts(
            [r.id for r in rows]),
    )
```

- [ ] **Step 5: Звузити `registrations_all` до нових хелперів**

У `registrations_all` замінити блок `query = _apply_registration_filters(...)`
на:

```python
    query = _apply_registration_filters(
        EventRegistration.query.options(*_registration_row_options()),
        filters,
    )

    pagination = query.order_by(EventRegistration.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False,
    )
    ctx = _registration_rows_context(pagination.items)
```

Три блоки, що рахували `referrer_map`, `quiz_states` і `surcharge_due` вручну
(разом із локальними імпортами `referral_service`, `quiz_service`,
`transfer_service`), прибрати. У `render_template` замість чотирьох ключів
(`referrer_map`, `quiz_states`, `quiz_statuses`, `surcharge_due`) передати один:
`ctx=ctx`.

- [ ] **Step 6: Прогнати тести реєстрацій**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_registration_columns.py tests/test_routes/test_admin_registrations_user_filter.py tests/test_routes/test_admin_registrations_return.py tests/test_routes/test_admin_registrations_export.py -q`
Expected: PASS -- усі. Це і є доказ, що рефактор нічого не змінив: ці тести
читають вміст рядка (посилання на захід, бейджі прогресу, форми дій).

- [ ] **Step 7: Прогнати сторожів розмітки й порівняти знімок**

Run: `venv/Scripts/python.exe -m pytest tests/test_design_system/ tests/test_lint_templates.py -q`
Expected: PASS.

Run: `venv/Scripts/python.exe tools/ds/html_snapshot.py capture --label after && venv/Scripts/python.exe tools/ds/html_snapshot.py diff before after`
Expected: код повернення 0 -- розбіжностей немає.

- [ ] **Step 8: Коміт**

```bash
git add app/templates/admin/partials/_registration_row.html app/templates/admin/registrations.html app/admin/routes_registrations.py
git commit -m "refactor(admin): рядок учасника реєстру -- один макрос на два місця"
```

---

### Task 2: Агрегати груп «курс -> дата»

Чисті числа, без UI. Сервіс віддає готову структуру груп і пагінацію по курсах;
маршрут із Task 5 лише передає йому відфільтрований запит.

**Files:**
- Create: `app/services/registration_groups.py`
- Test: `tests/test_services/test_registration_groups.py`

**Interfaces:**
- Consumes: `EventRegistration`, `CourseInstance`,
  `app.services.seating.occupied_counts`.
- Produces: `registration_groups.grouped_page(matched_query, page, per_page, oldest_first=False)`
  -> `(groups, pagination)`.
  `groups` -- список `SimpleNamespace(course, instances, total, confirmed,
  pending, cancelled, amount, paid, due)`; кожен елемент `instances` --
  `SimpleNamespace(instance, total, confirmed, pending, cancelled, amount,
  paid, due, occupied, capacity, overbooked)`.
  `pagination` -- обʼєкт Flask-SQLAlchemy по КУРСАХ (`.items` -- список
  `course_id`).

- [ ] **Step 1: Написати падаючий тест**

Створити `tests/test_services/test_registration_groups.py`:

```python
"""Агрегати режиму «За заходами»: число заголовка = те, що розгорнеться."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import registration_groups


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def two_dates(app):
    """Курс із двома датами: на ближчій -- дві реєстрації, на дальшій -- одна.

    Тільки flush: автоматична фікстура db_session відкочує транзакцію, а
    закомічений користувач переживав би тест і ламав чужі посторінкові тести.
    """
    course = Course(title=f'Курс {_uid()}', slug=f'grp-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()

    now = datetime.now(timezone.utc)
    instances = []
    for offset in (10, 20):
        inst = CourseInstance(
            course_id=course.id, status='published', event_format='offline',
            start_date=now + timedelta(days=offset),
        )
        db.session.add(inst)
        db.session.flush()
        instances.append(inst)

    def _reg(inst, status, payment_status, amount):
        user = User.create_with_password(
            f'grp-{_uid()}@test.com', 'password123',
            first_name='Г', last_name='Т',
        )
        db.session.flush()
        reg = EventRegistration(
            user_id=user.id, instance_id=inst.id, phone='+380670000000',
            specialty='T', workplace='Клініка', status=status,
            payment_status=payment_status, payment_amount=amount,
        )
        db.session.add(reg)
        db.session.flush()
        return reg

    _reg(instances[0], 'confirmed', 'paid', 3500)
    _reg(instances[0], 'pending', 'unpaid', 2975)
    _reg(instances[1], 'confirmed', 'paid', 4500)
    return course, instances


def _matched(status=None):
    query = db.session.query(EventRegistration.id)
    if status:
        query = query.filter(EventRegistration.status == status)
    return query


def _group_of(groups, course):
    return next(g for g in groups if g.course.id == course.id)


def test_group_sums_its_dates(two_dates):
    course, _ = two_dates
    groups, pagination = registration_groups.grouped_page(
        _matched(), page=1, per_page=25)

    group = _group_of(groups, course)
    assert group.total == 3
    assert group.confirmed == 2
    assert group.pending == 1
    assert group.amount == 3500 + 2975 + 4500
    assert group.paid == 3500 + 4500
    assert group.due == 2975
    assert pagination.total >= 1


def test_dates_carry_their_own_numbers(two_dates):
    course, instances = two_dates
    groups, _ = registration_groups.grouped_page(_matched(), page=1, per_page=25)

    by_id = {row.instance.id: row for row in _group_of(groups, course).instances}
    assert by_id[instances[0].id].total == 2
    assert by_id[instances[1].id].total == 1
    assert by_id[instances[0].id].due == 2975
    assert by_id[instances[1].id].due == 0


def test_filter_shrinks_the_numbers(two_dates):
    """Заголовок не сміє обіцяти більше, ніж розгорнеться."""
    course, instances = two_dates
    groups, _ = registration_groups.grouped_page(
        _matched(status='pending'), page=1, per_page=25)

    group = _group_of(groups, course)
    assert group.total == 1
    assert [row.instance.id for row in group.instances] == [instances[0].id]


def test_course_without_matches_disappears(two_dates):
    """Курс, у якого після фільтра нуль реєстрацій, у видачу не потрапляє."""
    course, _ = two_dates
    groups, _ = registration_groups.grouped_page(
        _matched(status='cancelled'), page=1, per_page=25)

    assert all(g.course.id != course.id for g in groups)


def test_oldest_first_flips_the_order(two_dates):
    course, instances = two_dates
    groups, _ = registration_groups.grouped_page(
        _matched(), page=1, per_page=25, oldest_first=True)

    assert [row.instance.id for row in _group_of(groups, course).instances] == [
        instances[0].id, instances[1].id]
```

- [ ] **Step 2: Прогнати тест і переконатись, що він падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_registration_groups.py -q`
Expected: FAIL -- `ModuleNotFoundError: No module named 'app.services.registration_groups'`

- [ ] **Step 3: Написати сервіс**

Створити `app/services/registration_groups.py`:

```python
"""Агрегати реєстрацій за курсами й датами -- режим «За заходами».

Сторінка цього режиму складається з ЧИСЕЛ: жодна реєстрація в ORM тут не
гідратується. Рядок учасника коштує батчів (стан тестування, анкета,
сертифікат, незакрита доплата), і платити їх за тисячі рядків, з яких
дивитимуться на десяток, немає за що -- самі рядки приїжджають окремим
маршрутом уже після кліку.
"""
from types import SimpleNamespace

from sqlalchemy import case, func, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.services.seating import occupied_counts


def grouped_page(matched_query, page, per_page, oldest_first=False):
    """Сторінка груп «курс -> дата» з підсумками.

    matched_query -- запит ID реєстрацій, що вже пройшли фільтри сторінки
    (`_apply_registration_filters(db.session.query(EventRegistration.id),
    filters)`). Саме він, а не власний набір умов: заголовок і вміст мусять
    рахуватись з одного джерела, інакше число в шапці обіцяє одне, а
    розгортання дає інше.

    Пагінація -- по КУРСАХ: вага сторінки не має залежати від числа
    реєстрацій під ними.
    """
    matched_ids = select(matched_query.subquery().c.id)
    instance_ids = select(EventRegistration.instance_id).where(
        EventRegistration.id.in_(matched_ids))

    order_col = (func.min(CourseInstance.start_date).asc() if oldest_first
                 else func.max(CourseInstance.start_date).desc())
    courses_stmt = select(CourseInstance.course_id).where(
        CourseInstance.id.in_(instance_ids),
    ).group_by(CourseInstance.course_id).order_by(order_col)
    # db.paginate віддає СКАЛЯРИ, тож у вибірці рівно одна колонка:
    # багатоколонковий select тут мовчки втратив би решту.
    pagination = db.paginate(courses_stmt, page=page, per_page=per_page,
                             error_out=False)
    course_ids = list(pagination.items)
    if not course_ids:
        return [], pagination

    counts = {
        row.instance_id: row
        for row in db.session.query(
            EventRegistration.instance_id.label('instance_id'),
            func.count(EventRegistration.id).label('total'),
            func.count(case((EventRegistration.status == 'confirmed', 1))).label('confirmed'),
            func.count(case((EventRegistration.status == 'pending', 1))).label('pending'),
            func.count(case((EventRegistration.status == 'cancelled', 1))).label('cancelled'),
            func.coalesce(func.sum(EventRegistration.payment_amount), 0).label('amount'),
            func.coalesce(func.sum(case((
                EventRegistration.payment_status == 'paid',
                EventRegistration.payment_amount))), 0).label('paid'),
        ).filter(
            EventRegistration.id.in_(matched_ids),
        ).group_by(EventRegistration.instance_id).all()
    }

    # Проведення гідратуємо -- на відміну від реєстрацій, їх стільки ж,
    # скільки рядків на екрані, а `effective_title` і
    # `effective_max_participants` -- це успадкування від курсу, якого
    # колонковим запитом не відтворити.
    instances = db.session.query(CourseInstance).options(
        joinedload(CourseInstance.course),
    ).filter(
        CourseInstance.course_id.in_(course_ids),
        CourseInstance.id.in_(instance_ids),
    ).all()
    occupied = occupied_counts([inst.id for inst in instances])

    by_course = {}
    for inst in instances:
        row = counts.get(inst.id)
        if row is None:
            continue
        capacity = inst.effective_max_participants
        taken = occupied.get(inst.id, 0)
        by_course.setdefault(inst.course_id, []).append(SimpleNamespace(
            instance=inst,
            total=row.total,
            confirmed=row.confirmed,
            pending=row.pending,
            cancelled=row.cancelled,
            amount=row.amount,
            paid=row.paid,
            due=row.amount - row.paid,
            occupied=taken,
            capacity=capacity,
            overbooked=capacity is not None and taken > capacity,
        ))

    groups = []
    for course_id in course_ids:
        rows = by_course.get(course_id)
        if not rows:
            continue
        # Заходи без дати (TBD) тримаємо скраю: None не порівняти з датою.
        rows.sort(key=lambda r: (r.instance.start_date is None,
                                 r.instance.start_date),
                  reverse=not oldest_first)
        groups.append(SimpleNamespace(
            course=rows[0].instance.course,
            instances=rows,
            total=sum(r.total for r in rows),
            confirmed=sum(r.confirmed for r in rows),
            pending=sum(r.pending for r in rows),
            cancelled=sum(r.cancelled for r in rows),
            amount=sum(r.amount for r in rows),
            paid=sum(r.paid for r in rows),
            due=sum(r.due for r in rows),
        ))
    return groups, pagination
```

- [ ] **Step 4: Прогнати тест і переконатись, що він проходить**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_registration_groups.py -q`
Expected: PASS -- усі пʼять.

- [ ] **Step 5: Коміт**

```bash
git add app/services/registration_groups.py tests/test_services/test_registration_groups.py
git commit -m "feat(admin): агрегати реєстрацій за курсами й датами"
```

---

### Task 3: Маршрут-фрагмент із рядками учасників

Окремий маршрут, який віддає готову таблицю учасників ОДНОГО заходу. Працює і
без сторінки з Task 5 -- перевіряється прямим GET.

**Files:**
- Modify: `app/admin/routes_registrations.py` (новий маршрут)
- Create: `app/templates/admin/partials/_registration_rows.html`
- Test: `tests/test_routes/test_admin_registrations_grouped.py`

**Interfaces:**
- Consumes: `_registration_row_options()`, `_registration_rows_context()`,
  макроси `registration_headers` / `registration_row` з Task 1.
- Produces: endpoint `admin.registration_group_rows`, URL
  `/admin/registrations/group/<int:instance_id>/rows`; приймає ті самі
  фільтри, що й сторінка, плюс `back` (куди повертати після дії в рядку).

- [ ] **Step 1: Написати падаючі тести**

Створити `tests/test_routes/test_admin_registrations_grouped.py`:

```python
"""Режим «За заходами»: фрагмент учасників і заголовки груп."""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'grp-adm-{_uid()}@test.com', 'password123',
        first_name='А', last_name='Д', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.flush()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _course(title=None):
    course = Course(
        title=title or f'Курс {_uid()}', slug=f'grp-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, days=14):
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _registration(inst, status='confirmed', payment_status='paid', amount=3500):
    user = User.create_with_password(
        f'grp-{_uid()}@test.com', 'password123', first_name='У', last_name='Ч')
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380670000000',
        specialty='T', workplace='Клініка', status=status,
        payment_status=payment_status, payment_amount=amount,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


@pytest.fixture
def event_with_two_people(app):
    course = _course()
    inst = _instance(course)
    regs = [
        _registration(inst, 'confirmed', 'paid', 3500),
        _registration(inst, 'pending', 'unpaid', 2975),
    ]
    return course, inst, regs


def test_rows_fragment_returns_only_its_event(client, admin, event_with_two_people):
    _, inst, regs = event_with_two_people
    other = _instance(_course(), days=21)
    stranger = _registration(other)
    _login(client, admin)

    html = client.get(
        f'/admin/registrations/group/{inst.id}/rows').get_data(as_text=True)

    for reg in regs:
        assert f'/admin/registrations/{reg.id}/edit' in html
    assert f'/admin/registrations/{stranger.id}/edit' not in html


def test_rows_fragment_honours_filters(client, admin, event_with_two_people):
    _, inst, regs = event_with_two_people
    pending = next(r for r in regs if r.status == 'pending')
    confirmed = next(r for r in regs if r.status == 'confirmed')
    _login(client, admin)

    html = client.get(
        f'/admin/registrations/group/{inst.id}/rows?status=pending'
    ).get_data(as_text=True)

    assert f'/admin/registrations/{pending.id}/edit' in html
    assert f'/admin/registrations/{confirmed.id}/edit' not in html


def test_rows_fragment_returns_to_the_open_panel(client, admin, event_with_two_people):
    """Дія в рядку мусить повертати на ТУ САМУ розгорнуту панель."""
    _, inst, _ = event_with_two_people
    back = f'/admin/registrations?view=grouped&open={inst.id}'
    _login(client, admin)

    html = client.get(
        f'/admin/registrations/group/{inst.id}/rows?back={quote(back, safe="")}'
    ).get_data(as_text=True)

    assert f'open={inst.id}' in html


def test_rows_fragment_rejects_foreign_back(client, admin, event_with_two_people):
    """`back` іде у приховане поле `next`, тобто в редірект: чужий хост -- ні."""
    _, inst, _ = event_with_two_people
    _login(client, admin)

    html = client.get(
        f'/admin/registrations/group/{inst.id}/rows?back=https://evil.test/x'
    ).get_data(as_text=True)

    assert 'evil.test' not in html


def test_rows_fragment_requires_permission(client, app, event_with_two_people):
    """Фрагмент -- ті самі дані, що й сторінка, отже й ті самі права."""
    _, inst, _ = event_with_two_people
    stranger = User.create_with_password(
        f'grp-nop-{_uid()}@test.com', 'password123',
        first_name='Б', last_name='П', email_confirmed=True,
    )
    db.session.flush()
    _login(client, stranger)

    response = client.get(f'/admin/registrations/group/{inst.id}/rows')

    assert response.status_code in (302, 403)
```

- [ ] **Step 2: Прогнати тести і переконатись, що вони падають**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_registrations_grouped.py -q`
Expected: FAIL -- 404 на `/admin/registrations/group/<id>/rows`.

- [ ] **Step 3: Додати шаблон фрагмента**

Створити `app/templates/admin/partials/_registration_rows.html`:

```jinja
{# Учасники ОДНОГО заходу -- відповідь маршруту `registration_group_rows`.

   Віддаємо цілу таблицю, а не голі <tr>: панель заходу вставляє відповідь
   як є, і кожна панель має власну шапку колонок. Сама шапка й рядок --
   ті самі макроси, що й у плаcкому списку. #}
{% from 'admin/partials/_registration_row.html' import registration_headers, registration_row %}
<div class="admin-table-wrap">
  <table class="admin-table admin-table--wide">
    <thead>
      <tr>
        {{ registration_headers() }}
      </tr>
    </thead>
    <tbody>
      {% for reg in registrations %}
      {{ registration_row(reg, ctx, back_url) }}
      {% endfor %}
    </tbody>
  </table>
</div>
{% if truncated %}
{# Клас беремо наявний: власного layout-файлу в цієї задачі немає, а CSS
   без жодного шаблону-споживача валить сторожа ds_audit. #}
<p class="admin-text-muted">
  Показано перших {{ registrations | length }}.
  <a href="{{ url_for('admin.instance_registrations', instance_id=instance_id) }}">
    {{ icon('open_in_new') }} Відкрити захід повністю
  </a>
</p>
{% endif %}
```

- [ ] **Step 4: Додати маршрут**

У `app/admin/routes_registrations.py`, після `registrations_all`:

```python
# Стеля рядків у панелі заходу. Вебінар на 300 осіб у розгорнутій панелі --
# це рівно та вага, від якої режим і тікав: далі -- на сторінку заходу,
# у неї є пагінація.
_GROUP_ROWS_LIMIT = 100


@admin_bp.route('/registrations/group/<int:instance_id>/rows')
@permission_required('registrations.view')
def registration_group_rows(instance_id):
    """Рядки учасників одного заходу -- фрагмент для розгорнутої панелі.

    Фільтри ті самі, що й на сторінці: панель мусить показувати рівно тих,
    кого порахував заголовок групи.
    """
    filters = _registration_filters()
    query = _apply_registration_filters(
        EventRegistration.query.options(*_registration_row_options()),
        filters,
    ).filter(EventRegistration.instance_id == instance_id)

    rows = query.order_by(EventRegistration.created_at.desc()).limit(
        _GROUP_ROWS_LIMIT + 1).all()
    truncated = len(rows) > _GROUP_ROWS_LIMIT
    rows = rows[:_GROUP_ROWS_LIMIT]

    # back приходить із клієнта і йде у приховане поле `next` рядкових форм --
    # тобто в редірект. Чужий хост тут означав би відкритий редірект.
    back_url = request.args.get('back', '')
    if not is_safe_redirect_url(back_url):
        back_url = url_for('admin.registrations_all', view='grouped')

    return render_template(
        'admin/partials/_registration_rows.html',
        registrations=rows,
        ctx=_registration_rows_context(rows),
        back_url=back_url,
        instance_id=instance_id,
        truncated=truncated,
    )
```

- [ ] **Step 5: Прогнати тести і сторожів розмітки**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_registrations_grouped.py tests/test_design_system/ -q`
Expected: PASS -- усі пʼять нових і вся дизайн-система. Червоний сторож тут
означає клас без правила або вигаданий токен.

- [ ] **Step 6: Коміт**

```bash
git add app/admin/routes_registrations.py app/templates/admin/partials/_registration_rows.html tests/test_routes/test_admin_registrations_grouped.py
git commit -m "feat(admin): фрагмент рядків учасників для розгорнутого заходу"
```

---

### Task 4: Компонент диклоужера в дизайн-системі

Компонент оголошується й ПОКАЗУЄТЬСЯ раніше, ніж ним починає користуватись
сторінка. Причина технічна, не церемоніальна: `test_block_is_on_showcase`
параметризований по всіх класах-блоках `admin.css`, тож клас без вітрини
робить збірку червоною в ту ж мить, коли зʼявляється в CSS.

**Files:**
- Modify: `app/static/css/admin.css` (компонент `admin-disclosure`)
- Modify: `app/templates/design_system/_tab_admin.html`
- Modify: `tests/test_design_system/catalog_gap_baseline.json` (лише якщо
  сторож вимагатиме -- і лише в бік зменшення)

**Interfaces:**
- Produces: класи `admin-disclosure`, `admin-disclosure__head`,
  `admin-disclosure__title`, `admin-disclosure__metrics`,
  `admin-disclosure__metric`, `admin-disclosure__chevron`,
  `admin-disclosure__panel`, `admin-disclosure--nested`. На них спираються
  розмітка Task 5 і скрипт Task 6.

- [ ] **Step 1: Звірити імена токенів**

Run: `grep -n "iprm-surface-inset:|iprm-border:|iprm-radius-md:|iprm-text-secondary:|iprm-transition:|iprm-white:|iprm-bg:" -E app/static/css/common.css`
Кожен токен, ужитий у наступному кроці, мусить бути в цьому виводі; вигаданий
валить `tests/test_design_system/test_css_markup_sync.py::test_every_token_named_outside_css_exists`.

Шкали відступів у цій дизайн-системі НЕМАЄ: родини `--iprm-space-*` не існує,
і сусідні компоненти в `admin.css` задають відступи буквальними px. Тому px для
відступів тут -- норма проєкту, а не недогляд. Забороненими лишаються голі
значення КОЛЬОРУ: колір, межа, тінь і радіус беруться токенами.

- [ ] **Step 2: Компонент у `admin.css`**

Дописати в кінець `app/static/css/admin.css` (клас оголошується ТУТ і більше
ніде -- інакше падає `test_component_ownership`):

```css
/* ===== Диклоужер: заголовок із підсумками + панель ===================== */
/* Рядок-група, що розгортається: реєстр «За заходами» кладе в нього курс,
   дату і таблицю учасників. Не <details>: панель дати вантажиться лениво,
   і стан потрібен в ARIA, а не лише у вигляді. */
.admin-disclosure {
  border: 1px solid var(--iprm-border);
  border-radius: var(--iprm-radius-md);
  background: var(--iprm-white);
  overflow: hidden;
}

.admin-disclosure__head {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 12px 16px;
  border: 0;
  background: var(--iprm-surface-inset);
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.admin-disclosure__head:hover {
  background: var(--iprm-bg);
}

.admin-disclosure__title {
  flex: 1 1 auto;
  font-weight: 600;
}

.admin-disclosure__metrics {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.admin-disclosure__metric {
  color: var(--iprm-text-secondary);
  white-space: nowrap;
}

.admin-disclosure__chevron {
  display: inline-flex;
  transition: transform var(--iprm-transition);
}

.admin-disclosure__head[aria-expanded="true"] .admin-disclosure__chevron {
  transform: rotate(90deg);
}

.admin-disclosure__panel {
  padding: 12px 16px;
}

.admin-disclosure--nested {
  margin: 8px 0;
}
```

- [ ] **Step 3: Показати компонент у каталозі**

Додати в `app/templates/design_system/_tab_admin.html`, після секції
«Реєстр (таблиця)»:

```jinja
    <h3 class="ds-section-heading">Диклоужер (група, що розгортається)</h3>
    <div class="ds-demo">
      <section class="admin-disclosure">
        <button type="button" class="admin-disclosure__head" aria-expanded="true" aria-controls="ds-disclosure-1">
          <span class="admin-disclosure__chevron" aria-hidden="true">{{ icon('chevron_right') }}</span>
          <span class="admin-disclosure__title">Базовий курс плазмотерапії</span>
          <span class="admin-disclosure__metrics">
            <span class="admin-disclosure__metric">19 реєстр.</span>
            <span class="admin-disclosure__metric">81 000 &#8372;</span>
            <span class="badge badge--pending">борг 11 000 &#8372;</span>
          </span>
        </button>
        <div class="admin-disclosure__panel" id="ds-disclosure-1">
          <div class="admin-disclosure admin-disclosure--nested">
            <button type="button" class="admin-disclosure__head" aria-expanded="false" aria-controls="ds-disclosure-2">
              <span class="admin-disclosure__chevron" aria-hidden="true">{{ icon('chevron_right') }}</span>
              <span class="admin-disclosure__title">15.03.2026 &middot; Київ</span>
              <span class="admin-disclosure__metrics">
                <span class="admin-disclosure__metric">12 реєстр.</span>
                <span class="admin-seats">9/12</span>
              </span>
            </button>
            <div class="admin-disclosure__panel" id="ds-disclosure-2" hidden></div>
          </div>
        </div>
      </section>
    </div>
    <p class="ds-hint">.admin-disclosure: заголовок із підсумками плюс панель; стан тримає aria-expanded на кнопці, --nested -- вкладений рівень. Панель може вантажитись лениво (реєстр «За заходами»).</p>
```

- [ ] **Step 4: Прогнати сторожів каталогу**

Run: `venv/Scripts/python.exe -m pytest tests/test_design_system/ -q`
Expected: PASS. `test_catalog_gap_baseline_only_shrinks` дозволяє базлайну лише
зменшуватись: якщо він вимагає правки, число в `catalog_gap_baseline.json`
має ЗМЕНШИТИСЬ, а не вирости.

- [ ] **Step 5: Коміт**

```bash
git add app/static/css/admin.css app/templates/design_system/_tab_admin.html tests/test_design_system/catalog_gap_baseline.json
git commit -m "feat(design-system): диклоужер -- група з підсумками, що розгортається"
```

---

### Task 5: Режим «За заходами» на сторінці

Фільтр `view`, перемикач і шаблон із заголовками. Учасників сторінка не малює:
дата віддає посилання на захід, а панель наповнить JS із Task 6. Це і є
baseline без JS.

**Files:**
- Modify: `app/admin/routes_registrations.py` (`_registration_filters`,
  `registrations_all`, новий `_registration_page_context`)
- Create: `app/static/css/page-admin-registrations.css`
- Create: `app/templates/admin/registrations_grouped.html`
- Create: `app/templates/admin/partials/_registrations_view_switch.html`
- Modify: `app/templates/admin/registrations.html` (вставити перемикач)
- Test: `tests/test_routes/test_admin_registrations_grouped.py` (дописати)

**Interfaces:**
- Consumes: `registration_groups.grouped_page(...)` з Task 2, endpoint
  `admin.registration_group_rows` з Task 3.
- Produces: URL `/admin/registrations?view=grouped`.
- Produces: `routes_registrations._registration_page_context(filters, stats)`
  -> `dict` спільних для обох режимів ключів шаблону.
- Produces: розмітку з `data-group-total`, `data-instance-id`, `data-rows-url`,
  `aria-expanded`, `aria-controls` -- на них стоїть JS із Task 6.

- [ ] **Step 1: Дописати падаючі тести**

Додати в `tests/test_routes/test_admin_registrations_grouped.py`:

```python
def test_grouped_view_shows_course_and_date(client, admin, event_with_two_people):
    course, inst, _ = event_with_two_people
    _login(client, admin)

    html = client.get('/admin/registrations?view=grouped').get_data(as_text=True)

    assert course.title in html
    assert f'data-instance-id="{inst.id}"' in html
    assert f'/admin/registrations/group/{inst.id}/rows' in html
    assert f'/admin/instances/{inst.id}/registrations' in html


def test_grouped_numbers_follow_the_filter(client, admin, event_with_two_people):
    """Заголовок не сміє обіцяти більше, ніж розгорнеться."""
    _, inst, _ = event_with_two_people
    _login(client, admin)

    full = client.get('/admin/registrations?view=grouped').get_data(as_text=True)
    narrowed = client.get(
        '/admin/registrations?view=grouped&status=pending').get_data(as_text=True)

    assert f'data-instance-id="{inst.id}" data-group-total="2"' in full
    assert f'data-instance-id="{inst.id}" data-group-total="1"' in narrowed


def test_empty_group_disappears_under_filter(client, admin, event_with_two_people):
    course, inst, _ = event_with_two_people
    _login(client, admin)

    html = client.get(
        '/admin/registrations?view=grouped&status=cancelled').get_data(as_text=True)

    assert f'data-instance-id="{inst.id}"' not in html


def test_grouped_page_does_not_grow_with_events(client, admin):
    """Сторінка -- це числа. 12 заходів мусять коштувати як 2."""
    from sqlalchemy import event as sa_event

    _login(client, admin)

    def _count():
        seen = []

        def _tap(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith('SELECT'):
                seen.append(statement)

        sa_event.listen(db.engine, 'before_cursor_execute', _tap)
        try:
            client.get('/admin/registrations?view=grouped&scope=all')
        finally:
            sa_event.remove(db.engine, 'before_cursor_execute', _tap)
        return len(seen)

    course = _course()
    for _ in range(2):
        _registration(_instance(course))
    db.session.flush()
    few = _count()

    for _ in range(10):
        _registration(_instance(course))
    db.session.flush()
    many = _count()

    assert many - few <= 2, (
        f'12 заходів замість 2 дали +{many - few} SELECT ({few} -> {many}) -- '
        f'схоже, підсумки рахуються поштучно'
    )
```

- [ ] **Step 2: Прогнати тести і переконатись, що вони падають**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_registrations_grouped.py -q`
Expected: FAIL на нових чотирьох -- `view=grouped` поки віддає плаский список,
`data-instance-id` у ньому немає.

- [ ] **Step 3: Додати фільтр `view` і гілку в маршрут**

У `_registration_filters()`, поруч зі `scope`:

```python
        # Режим перегляду -- такий самий фільтр, як решта: інакше він злітав
        # би з кожної пілюлі, пагінації й «Застосувати».
        'view': _listing.choice_arg('view', ('list', 'grouped'), 'list'),
```

Спільний контекст шаблона винести з `registrations_all` у окрему функцію:

```python
def _registration_page_context(filters, stats):
    """Ключі, однакові для обох режимів реєстру: пілюлі, пресети, довідники."""
    return dict(
        stats=stats,
        filters=filters,
        filter_args=_listing.filter_args(filters),
        presets=[
            (key, preset['label'], preset['icon'], _preset_args(key))
            for key, preset in REGISTRATION_PRESETS.items()
        ],
        active_preset=next(
            (key for key in REGISTRATION_PRESETS
             if _preset_matches(key, filters)), None,
        ),
        status_options=EventRegistration.STATUSES,
        payment_options=EventRegistration.PAYMENT_STATUSES,
        method_options=EventRegistration.PAYMENT_METHODS,
        per_page_options=_listing.PER_PAGE_OPTIONS,
        **_registration_select_options(),
    )
```

У `registrations_all`, одразу після обчислення `stats`:

```python
    if filters['view'] == 'grouped':
        from app.services import registration_groups
        groups, pagination = registration_groups.grouped_page(
            _apply_registration_filters(
                db.session.query(EventRegistration.id), filters),
            page=page,
            # На цій сторінці рядок -- курс, а не реєстрація: 200 курсів
            # на екрані не читає ніхто.
            per_page=min(per_page, 25),
            oldest_first=filters['scope'] == 'upcoming',
        )
        return render_template(
            'admin/registrations_grouped.html',
            groups=groups, pagination=pagination,
            **_registration_page_context(filters, stats),
        )
```

Виклик `render_template` у гілці плаского списку звести до трьох власних
ключів (`registrations`, `pagination`, `ctx`) плюс
`**_registration_page_context(filters, stats)`.

- [ ] **Step 4: Перемикач режиму окремим партіалом**

Створити `app/templates/admin/partials/_registrations_view_switch.html`:

```jinja
{# Перемикач режиму реєстру -- спільний для плаского списку і для груп.
   Обидва шаблони показують ті самі дві пілюлі; копія розійшлася б на
   першому ж новому режимі. #}
{% macro view_switch(filters, filter_args) %}
<div class="admin-pills">
  {% for value, label, ico in [
       ('list', 'Список', 'format_list_bulleted'),
       ('grouped', 'За заходами', 'account_tree')] %}
  <a href="{{ url_for('admin.registrations_all', **dict(filter_args, view=value)) }}"
     class="admin-pill{% if filters.view == value %} admin-pill--active{% endif %}">
    {{ icon(ico) }} {{ label }}
  </a>
  {% endfor %}
</div>
{% endmacro %}
```

У `registrations.html` додати імпорт
`{% from 'admin/partials/_registrations_view_switch.html' import view_switch %}`
і виклик `{{ view_switch(filters, filter_args) }}` одразу після блоку
`stat_cards`.

Іконку `account_tree` звірити з набором:
`grep -n "account_tree" app/static/icons/*.json app/services/icons*.py 2>/dev/null` --
якщо її в субсеті немає, узяти наявну (наприклад `list_alt`), інакше
`tests/test_icons.py` покаже сире слово замість гліфа.

- [ ] **Step 5: Layout сторінки окремим файлом**

Створити `app/static/css/page-admin-registrations.css`. Файл заводиться саме
тут, разом із розміткою, що його вживає, і підключається РІВНО з одного
шаблону -- `registrations_grouped.html`. Два споживачі зробили б його
компонентним за правилом проєкту, і тоді ім'я `page-` стало б хибним.

Шкали відступів у дизайн-системі немає (родини `--iprm-space-*` не існує), тож
px тут -- норма: сусідні `page-admin-*.css` роблять так само. Кольору, шрифта,
межі й тіні в цьому файлі бути не повинно -- це layout.

```css
/* Layout реєстру «За заходами»: лише сітка й відступи рівнів.
   Декор (колір, шрифт, межа, тінь) живе в компонентах admin.css. */
.registrations-groups {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.registrations-groups__dates {
  padding-left: 24px;
}

.registrations-groups__fallback {
  margin: 8px 0 0;
}
```

- [ ] **Step 6: Шаблон згрупованого режиму**

Створити `app/templates/admin/registrations_grouped.html`:

```jinja
{% extends "admin/base_admin.html" %}

{% block title %}Реєстрації за заходами | ІПРМ{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/admin.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/admin-quiz.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/modal.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-admin-registrations.css') }}?v={{ assets_version }}">
{% endblock %}

{% from 'admin/partials/_filter_bar.html' import filter_bar, pager, empty_state, stat_cards %}
{% from 'admin/partials/_registrations_view_switch.html' import view_switch %}
{% from 'partials/_money.html' import money %}

{% block content %}
{# Куди повернутись після дії в рядку: поточний URL разом із фільтрами і
   переліком розгорнутих панелей (?open=). Без цього кожна дія згортала б
   усе назад. #}
{% set back_url = request.full_path.rstrip('?') %}
<div class="admin-with-sidebar">
  {% include 'admin/partials/_sidebar.html' %}
  <div class="admin-layout admin-layout--wide">

    <div class="admin-hero">
      <div>
        <div class="admin-breadcrumb">
          <a href="{{ url_for('admin.courses_list') }}" class="admin-breadcrumb__link">Панель</a>
          <span class="admin-breadcrumb__sep">/</span>
          <span class="admin-breadcrumb__current">Реєстрації</span>
        </div>
        <h1 class="admin-hero__title">Реєстрації за заходами</h1>
        <p class="admin-hero__subtitle">
          Курс, під ним дати проведення, у даті &mdash; зареєстровані.
          Числа в заголовках рахуються тими самими фільтрами, що й список.
        </p>
      </div>
    </div>

    {% include 'partials/flash_messages.html' %}

    {{ stat_cards([{'value': stats.total, 'label': 'Всього'},
                   {'value': stats.confirmed, 'label': 'Підтверджено', 'mod': 'success'},
                   {'value': stats.pending, 'label': 'Очікує', 'mod': 'warning'},
                   {'value': stats.cancelled, 'label': 'Скасовано', 'mod': 'danger'},
                   {'value': money(stats.total_paid), 'label': 'Оплачено', 'mod': 'accent'}]) }}

    {{ view_switch(filters, filter_args) }}

    <div class="admin-pills">
      {% for value, label, ico in [
           ('upcoming', 'Майбутні заходи', 'event_upcoming'),
           ('past', 'Минулі', 'history'),
           ('all', 'Усі', 'format_list_bulleted')] %}
      <a href="{{ url_for('admin.registrations_all', **dict(filter_args, scope=value)) }}"
         class="admin-pill{% if filters.scope == value %} admin-pill--active{% endif %}">
        {{ icon(ico) }} {{ label }}
      </a>
      {% endfor %}
    </div>

    <div class="admin-pills admin-pills--presets">
      {% for key, label, ico, args in presets %}
      <a href="{{ url_for('admin.registrations_all', scope=filters.scope, view='grouped', **args) }}"
         class="admin-pill{% if active_preset == key %} admin-pill--active{% endif %}">
        {{ icon(ico) }} {{ label }}
      </a>
      {% endfor %}
    </div>

    {{ filter_bar(
         endpoint='admin.registrations_all',
         values=filters,
         search={'name': 'q', 'placeholder': 'Пошук за іменем, email або телефоном'},
         fields=[
           {'name': 'status', 'label': 'Статус', 'placeholder': 'Всі статуси', 'options': status_options},
           {'name': 'payment', 'label': 'Оплата', 'placeholder': 'Всі оплати', 'options': payment_options},
           {'name': 'payment_method', 'label': 'Спосіб оплати', 'placeholder': 'Всі способи', 'options': method_options},
           {'name': 'course_id', 'label': 'Курс', 'placeholder': 'Всі курси', 'options': course_options},
           {'name': 'trainer_id', 'label': 'Тренер', 'placeholder': 'Всі тренери', 'options': trainer_options},
           {'name': 'instance_id', 'label': 'Захід', 'placeholder': 'Всі заходи', 'options': instance_options},
           {'name': 'date_from', 'label': 'Реєстрації з', 'type': 'date'},
           {'name': 'date_to', 'label': 'Реєстрації по', 'type': 'date'},
           {'name': 'no_certificate', 'label': 'Сертифікат',
            'placeholder': 'Будь-який', 'options': [('1', 'Ще не виданий')]},
           {'name': 'surcharge', 'label': 'Доплата',
            'placeholder': 'Будь-яка', 'options': [('due', 'Не надійшла')]},
           {'name': 'per_page', 'label': 'Курсів на сторінці', 'placeholder': '25 (типово)', 'options': per_page_options, 'narrowing': False},
         ],
         base_args={'scope': filters.scope, 'user_id': filters.user_id, 'view': 'grouped'},
         export_endpoint='admin.registrations_export',
       ) }}

    {% if groups %}
    <div class="registrations-groups">
      {% for group in groups %}
      <section class="admin-disclosure">
        <button type="button" class="admin-disclosure__head"
                aria-expanded="true" aria-controls="course-{{ group.course.id }}">
          <span class="admin-disclosure__chevron" aria-hidden="true">{{ icon('chevron_right') }}</span>
          <span class="admin-disclosure__title">{{ group.course.title }}</span>
          <span class="admin-disclosure__metrics">
            <span class="admin-disclosure__metric">{{ group.total }} реєстр.</span>
            <span class="admin-disclosure__metric">{{ money(group.amount) }}</span>
            {% if group.due %}
            <span class="badge badge--pending">борг {{ money(group.due) }}</span>
            {% endif %}
          </span>
        </button>
        <div class="admin-disclosure__panel registrations-groups__dates" id="course-{{ group.course.id }}">
          {% for row in group.instances %}
          <div class="admin-disclosure admin-disclosure--nested">
            <button type="button" class="admin-disclosure__head"
                    aria-expanded="false" aria-controls="inst-{{ row.instance.id }}"
                    data-instance-id="{{ row.instance.id }}" data-group-total="{{ row.total }}"
                    data-rows-url="{{ url_for('admin.registration_group_rows', instance_id=row.instance.id, **dict(filter_args, back=back_url)) }}">
              <span class="admin-disclosure__chevron" aria-hidden="true">{{ icon('chevron_right') }}</span>
              <span class="admin-disclosure__title">
                {{ row.instance.effective_title }}
                <span class="admin-text-muted">
                  {{ row.instance.start_date.strftime('%d.%m.%Y') if row.instance.start_date else 'без дати' }}
                  {%- if row.instance.location %} &middot; {{ row.instance.location }}{% endif %}
                </span>
              </span>
              <span class="admin-disclosure__metrics">
                <span class="admin-disclosure__metric">{{ row.total }} реєстр.</span>
                <span class="badge badge--active">{{ row.confirmed }}</span>
                <span class="badge badge--pending">{{ row.pending }}</span>
                {% if row.cancelled %}<span class="badge badge--cancelled">{{ row.cancelled }}</span>{% endif %}
                <span class="admin-disclosure__metric">{{ money(row.amount) }}</span>
                {% if row.due %}
                <span class="badge badge--pending">борг {{ money(row.due) }}</span>
                {% endif %}
                {% if row.capacity %}
                <span class="admin-seats{% if row.overbooked %} admin-seats--over{% endif %}">{{ row.occupied }}/{{ row.capacity }}</span>
                {% endif %}
              </span>
            </button>
            {# Без JS панель лишається згорнутою, і єдиний шлях до людей --
               посилання всередині. Саме тому воно тут, а не лише в меню. #}
            <div class="admin-disclosure__panel" id="inst-{{ row.instance.id }}" hidden>
              <p class="registrations-groups__fallback">
                <a href="{{ url_for('admin.instance_registrations', instance_id=row.instance.id) }}">
                  {{ icon('open_in_new') }} Відкрити захід
                </a>
              </p>
            </div>
          </div>
          {% endfor %}
        </div>
      </section>
      {% endfor %}
    </div>

    {{ pager('admin.registrations_all', pagination, filter_args) }}
    {% else %}
    {% call empty_state('admin.registrations_all', filter_args,
                        base_args={'scope': filters.scope, 'view': 'grouped'},
                        narrow_args={'user_id': filters.user_id, 'per_page': False},
                        icon_name='how_to_reg', title='Реєстрацій немає') %}
      <p>На цьому зрізі жоден захід не має реєстрацій.
        <a href="{{ url_for('admin.registrations_all', view='grouped', scope='all') }}">Показати всі заходи</a>.</p>
    {% endcall %}
    {% endif %}

  </div>
</div>
{% include 'admin/partials/_transfer_modal.html' %}
{% endblock %}
```

`data-instance-id` і `data-group-total` стоять саме в такому порядку і поруч --
на це спирається `test_grouped_numbers_follow_the_filter`.

- [ ] **Step 7: Прогнати тести сторінки**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_registrations_grouped.py tests/test_lint_templates.py -q`
Expected: PASS -- усі девʼять. `test_grouped_page_does_not_grow_with_events`
мусить бути зеленим без жодних додаткових правок: сторінка не гідратує
реєстрацій.

- [ ] **Step 8: Коміт**

```bash
git add app/admin/routes_registrations.py app/static/css/page-admin-registrations.css app/templates/admin/registrations_grouped.html app/templates/admin/partials/_registrations_view_switch.html app/templates/admin/registrations.html tests/test_routes/test_admin_registrations_grouped.py
git commit -m "feat(admin): режим «За заходами» у реєстрі реєстрацій"
```

---

### Task 6: Розгортання і памʼять про відкрите

**Files:**
- Create: `app/static/js/admin-registrations-grouped.js`
- Modify: `app/templates/admin/registrations_grouped.html` (блок `extra_scripts`)

**Interfaces:**
- Consumes: `data-rows-url`, `aria-expanded`, `aria-controls`,
  `data-instance-id` з розмітки Task 5, класи `admin-disclosure*` з Task 4.
- Produces: параметр `?open=<instance_id>[,<instance_id>]` на сторінці режиму.

- [ ] **Step 1: Скрипт розгортання**

Створити `app/static/js/admin-registrations-grouped.js`:

```javascript
/* admin-registrations-grouped.js -- розгортання груп у реєстрі «За заходами».

   Заголовок курсу згортає свою панель. Заголовок дати додатково тягне рядки
   учасників (data-rows-url) -- рівно один раз: повторне розгортання показує
   вже завантажене.

   Відкриті дати живуть у ?open=<id>,<id>: дія в рядку робить редірект на
   `next`, і без цього менеджер щоразу повертався б до згорнутого екрана.

   Рядок після вставки нічим не ініціалізується: admin-inline-edit,
   admin-copy-link, admin-transfer і modal слухають document через
   делегування, а меню дій -- нативний <details>. */
(function () {
  'use strict';

  var OPEN_PARAM = 'open';

  function panelOf(head) {
    var id = head.getAttribute('aria-controls');
    return id ? document.getElementById(id) : null;
  }

  function currentlyOpen() {
    var heads = document.querySelectorAll(
      '[data-instance-id][aria-expanded="true"]');
    return Array.prototype.map.call(heads, function (head) {
      return head.getAttribute('data-instance-id');
    });
  }

  function rememberOpen() {
    var ids = currentlyOpen();
    var url = new URL(window.location.href);
    if (ids.length) {
      url.searchParams.set(OPEN_PARAM, ids.join(','));
    } else {
      url.searchParams.delete(OPEN_PARAM);
    }
    window.history.replaceState({}, '', url.toString());
  }

  function load(head, panel) {
    var url = head.getAttribute('data-rows-url');
    if (!url || head.getAttribute('data-loaded') === '1') return;
    head.setAttribute('data-loaded', '1');
    panel.innerHTML = '<p class="registrations-groups__fallback">Завантаження...</p>';
    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
    }).then(function (response) {
      if (!response.ok) throw new Error(response.status);
      return response.text();
    }).then(function (html) {
      panel.innerHTML = html;
      // Іконки в субсеті без лігатур: вставлений фрагмент треба полагодити.
      if (window.msFixIcons) window.msFixIcons(panel);
    }).catch(function () {
      head.removeAttribute('data-loaded');
      panel.innerHTML = '<p class="registrations-groups__fallback">'
        + 'Не вдалося завантажити учасників. '
        + '<button type="button" class="btn-admin btn-admin--secondary btn-admin--sm" '
        + 'data-rows-retry>Спробувати ще</button></p>';
    });
  }

  function toggle(head, expand) {
    var panel = panelOf(head);
    if (!panel) return;
    head.setAttribute('aria-expanded', expand ? 'true' : 'false');
    panel.hidden = !expand;
    if (expand) load(head, panel);
    if (head.hasAttribute('data-instance-id')) rememberOpen();
  }

  document.addEventListener('click', function (event) {
    var retry = event.target.closest('[data-rows-retry]');
    if (retry) {
      var panel = retry.closest('.admin-disclosure__panel');
      var owner = panel && document.querySelector(
        '[aria-controls="' + panel.id + '"]');
      if (owner) load(owner, panel);
      return;
    }
    var head = event.target.closest('.admin-disclosure__head');
    if (!head) return;
    toggle(head, head.getAttribute('aria-expanded') !== 'true');
  });

  document.addEventListener('DOMContentLoaded', function () {
    var raw = new URLSearchParams(window.location.search).get(OPEN_PARAM);
    (raw ? raw.split(',') : []).forEach(function (id) {
      if (!id) return;
      var head = document.querySelector('[data-instance-id="' + id + '"]');
      if (head) toggle(head, true);
    });
  });
}());
```

- [ ] **Step 2: Підключити скрипти**

У `app/templates/admin/registrations_grouped.html` додати наприкінці файлу:

```jinja
{% block extra_scripts %}
{{ super() }}
<script src="{{ url_for('static', filename='js/admin-copy-link.js') }}?v={{ assets_version }}" defer></script>
<script src="{{ url_for('static', filename='js/admin-inline-edit.js') }}?v={{ assets_version }}" defer></script>
<script src="{{ url_for('static', filename='js/modal.js') }}?v={{ assets_version }}" defer></script>
<script src="{{ url_for('static', filename='js/admin-transfer.js') }}?v={{ assets_version }}" defer></script>
<script src="{{ url_for('static', filename='js/admin-registrations-grouped.js') }}?v={{ assets_version }}" defer></script>
{% endblock %}
```

- [ ] **Step 3: Прогнати тести сторінки**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_registrations_grouped.py tests/test_design_system/ -q`
Expected: PASS -- усе. Скрипт розмітки не змінює, тож червоний тут означає
зламаний шаблон, а не JS.

- [ ] **Step 4: Подивитись сторінку очима**

Run: `venv/Scripts/python.exe run.py` і відкрити
`http://127.0.0.1:5000/admin/registrations?view=grouped` адміном.
Перевірити руками: курс згортається; дата розгортається і тягне таблицю;
повторне згортання-розгортання НЕ шле другий запит (вкладка Network);
у рядку працюють селекти статусу й оплати; після дії в рядку сторінка
повертається з тією самою розгорнутою панеллю (`?open=` в адресі).

- [ ] **Step 5: Коміт**

```bash
git add app/static/js/admin-registrations-grouped.js app/templates/admin/registrations_grouped.html
git commit -m "feat(admin): розгортання заходів із лінивим довантаженням учасників"
```

---

### Task 7: Документація і повний прогін

**Files:**
- Modify: `docs/routes.md`

**Interfaces:**
- Consumes: режим сторінки з Task 5 і компонент із Task 4.

- [ ] **Step 1: Описати режим у документації маршрутів**

У `docs/routes.md`, у розділі адмінки поруч із `/admin/registrations`, додати:

```markdown
- `GET /admin/registrations?view=grouped` -- той самий реєстр, згрупований
  «курс -> дата -> учасники». Числа в заголовках рахуються тими самими
  фільтрами; рядки учасників довантажує
  `GET /admin/registrations/group/<instance_id>/rows` (стеля -- 100 рядків,
  далі -- на сторінку заходу).
```

- [ ] **Step 2: Повний прогін**

Run: `venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS -- уся збірка. Окремо звірити, що не впав
`tests/test_routes/test_api_v1_clients.py`: він падає, коли тест лишив по собі
закомічених користувачів.

- [ ] **Step 3: Коміт**

```bash
git add docs/routes.md
git commit -m "docs(routes): режим «За заходами» у переліку маршрутів"
```

---

## Перевірене вручну до написання плану

Щоб задачі не спіткнулись на здогадах, три речі перевірені на живому коді:

1. **Макрос бачить імпорти свого партіала.** `{% import %}` на верхівці
   `_registration_row.html` доступний усередині його макросів -- перевірено
   на ізольованому Jinja-середовищі.
2. **`db.paginate` віддає СКАЛЯРИ.** `select(a, b, c).group_by(...)` через
   `db.paginate` мовчки втрачає всі колонки крім першої (`.items` -- список
   `int`). Тому в `grouped_page` у вибірці рівно одна колонка -- `course_id`;
   `total` і `pages` при цьому рахуються по групах правильно.
3. **Агрегат через `IN (підзапит)` працює** на тому ж діалекті, що й наявний
   фільтр «Доплата: не надійшла»: `EventRegistration.id.in_(select(...))`.

## Чого в плані немає (за спекою)

* Сторінка одного заходу `instance_registrations.html` не змінюється.
* Окремого XLSX під згрупований вигляд немає: експорт лишається плаcким
  зрізом за тими самими фільтрами.
* Кнопки «розгорнути все» немає: на сторінці з пагінацією по курсах вона
  означала б десятки запитів одним кліком.
