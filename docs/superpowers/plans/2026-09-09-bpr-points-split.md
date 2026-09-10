# Бали БПР: дробові значення та розподіл за форматом -- план реалізації

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бали БПР зберігаються дробовими і задаються окремо для онлайн- та офлайн-участі, а кожен учасник отримує бали свого формату.

**Architecture:** Одна колонка `cpd_points` на курсі й проведенні розщеплюється на `cpd_points_online` / `cpd_points_offline` типу `Numeric(5,2)`; реєстрація отримує власний `participation_format`, з якого рахується `due_cpd_points`. Порядок робіт -- expand/contract: спершу поруч зі старою колонкою з'являються нові (Task 3), далі споживачі по одному переїжджають на них (Tasks 4-9), і аж тоді стара колонка й тимчасова властивість зникають (Task 10), а міграція пишеться останньою (Task 11).

**Tech Stack:** Flask, SQLAlchemy, Alembic, WTForms, Jinja2, pytest, vanilla JS (без збірок).

**Spec:** `docs/superpowers/specs/2026-09-09-bpr-points-split-design.md`

## Global Constraints

- Жодних емодзі в коді, шаблонах, повідомленнях і комітах.
- No Inline Policy: ніякого інлайнового JS чи CSS у шаблонах; скрипти -- окремими файлами в `app/static/js/`, підключення `<script src="{{ url_for('static', filename='js/NAME.js') }}?v={{ assets_version }}"></script>` перед `{% endblock %}`.
- Дизайн-система -- джерело істини: декор компонента оголошується один раз у компонентному CSS; `page-*.css` -- лише layout.
- Тип балів у БД: `Numeric(5,2)`, nullable.
- CHECK-констрейнт на кожну нову колонку балів: `>= 0 OR IS NULL`.
- `participation_format`: `String(20)`, `CHECK IN ('online','offline') OR NULL`.
- Гілки не заводимо -- комітимо напряму в `main`. Push НЕ робимо: його виконує людина.
- Кожен коміт закінчується рядком `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Кількість alembic-голів дізнаватись командою `flask db heads`, а не грепом по файлах ревізій.
- Тести, що створюють користувачів, прибирають їх у teardown -- інакше валиться `tests/test_routes/test_api_v1.py::test_api_v1_clients`.
- Уся тестова база -- SQLite in-memory через `create_all()` з моделей (`tests/conftest.py`), тож міграції в загальному прогоні НЕ виконуються. Тест міграції імпортує модуль ревізії й перевіряє його helper-функції, як `tests/test_db/test_migration_bpr_counter.py`.
- Команда прогону: `python -m pytest <шлях> -v`.

### Передумова поза цим репозиторієм (блокує ЛИШЕ деплой, не роботу)

`D:\site-mm-medic` дзеркалить ключ `cpd_points` у колонку `db.Integer`. Task 8 цей ключ прибирає. Правка mm-medic -- окрема задача в тому репозиторії; вона мусить бути в проді РАНІШЕ за цю. Розробку за цим планом вона не блокує.

---

### Task 1: Розбір і показ дробових балів

Спільні `parse_points` (рядок -> `Decimal`) і `format_points` (`Decimal` -> рядок без хвостових нулів) плюс Jinja-фільтр `points`. Далі ними користуються геть усі задачі, тому вони йдуть першими.

**Files:**
- Modify: `app/utils.py` (додати після `normalize_name`)
- Modify: `app/i18n_plurals.py` (додати наприкінці файлу)
- Modify: `app/__init__.py:217` (реєстрація фільтра поряд з `plural`)
- Test: `tests/test_services/test_points_format.py` (створити)

**Interfaces:**
- Consumes: нічого.
- Produces:
  - `app.utils.parse_points(raw) -> Decimal | None` -- приймає `'4,5'`, `'4.5'`, `'9'`, `4.5`, `Decimal('4.5')`; `None` і порожній рядок -> `None`; сміття -> `ValueError`. Результат квантований до двох знаків з `ROUND_HALF_UP`.
  - `app.utils.format_points(value, sep=',') -> str` -- `Decimal('9.00') -> '9'`, `Decimal('7.50') -> '7,5'`, `None -> ''`.
  - `app.i18n_plurals.points_text(value) -> str` -- те саме, але роздільник за активною локаллю (`.` для `en`, `,` для решти).
  - Jinja-фільтр `points` == `points_text`.

- [ ] **Step 1: Написати падаючий тест**

Створити `tests/test_services/test_points_format.py`:

```python
from decimal import Decimal

import pytest

from app.i18n_plurals import points_text
from app.utils import format_points, parse_points


@pytest.mark.parametrize('raw, expected', [
    ('4,5', Decimal('4.50')),
    ('4.5', Decimal('4.50')),
    ('9', Decimal('9.00')),
    (' 7,5 ', Decimal('7.50')),
    (4.5, Decimal('4.50')),
    (Decimal('4.5'), Decimal('4.50')),
])
def test_parse_points_accepts_both_separators(raw, expected):
    assert parse_points(raw) == expected


@pytest.mark.parametrize('raw', [None, '', '   '])
def test_parse_points_empty_is_none(raw):
    assert parse_points(raw) is None


@pytest.mark.parametrize('raw', ['abc', '4,5,6', '--1'])
def test_parse_points_rejects_garbage(raw):
    with pytest.raises(ValueError):
        parse_points(raw)


@pytest.mark.parametrize('value, expected', [
    (Decimal('9.00'), '9'),
    (Decimal('7.50'), '7,5'),
    (Decimal('4.55'), '4,55'),
    (Decimal('100.00'), '100'),
    (None, ''),
])
def test_format_points_trims_trailing_zeros(value, expected):
    assert format_points(value) == expected


def test_format_points_custom_separator():
    assert format_points(Decimal('7.50'), sep='.') == '7.5'


def test_points_text_uses_dot_for_english(app):
    from flask_babel import force_locale
    with app.test_request_context('/'):
        with force_locale('en'):
            assert points_text(Decimal('7.50')) == '7.5'
        with force_locale('uk'):
            assert points_text(Decimal('7.50')) == '7,5'
```

- [ ] **Step 2: Прогнати тест і переконатись, що падає**

Run: `python -m pytest tests/test_services/test_points_format.py -v`
Expected: FAIL -- `ImportError: cannot import name 'parse_points' from 'app.utils'`

- [ ] **Step 3: Реалізувати `parse_points` і `format_points`**

У `app/utils.py` додати до імпортів `from decimal import Decimal, InvalidOperation, ROUND_HALF_UP` і функції:

```python
# Бали БПР бувають дробові (4,5 / 7,5), а вводяться людьми, тобто прийти
# може і кома, і крапка, і нерозривний пробіл із Excel. Розбір один на всі
# точки входу: WTForms-поле, xlsx-імпорт, форма підтвердження присутності.
POINTS_QUANT = Decimal('0.01')


def parse_points(raw):
    """Рядок або число -> Decimal з двома знаками. Порожнє -> None.

    Приймає кому і крапку як роздільник. Нерозбірне значення -- ValueError,
    щоб виклик показав людині рядок, а не мовчки записав None.
    """
    if raw is None:
        return None
    text = str(raw).strip().replace('\u00a0', '').replace(' ', '').replace(',', '.')
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f'не число: {raw!r}')
    if not value.is_finite():
        raise ValueError(f'не число: {raw!r}')
    return value.quantize(POINTS_QUANT, rounding=ROUND_HALF_UP)


def format_points(value, sep=','):
    """Decimal -> рядок без хвостових нулів: 9.00 -> '9', 7.50 -> '7,5'.

    `sep` окремим аргументом, бо той самий нормалізатор збирає ім'я файлу
    розетки на сертифікаті, а там роздільник -- крапка.
    """
    if value is None or value == '':
        return ''
    number = Decimal(str(value))
    # normalize() зрізає хвостові нулі, але ціле сотнями віддає як 1E+2 --
    # тому цілі окремо зводимо до звичайного запису.
    number = number.normalize()
    if number == number.to_integral_value():
        number = number.quantize(Decimal(1))
    return format(number, 'f').replace('.', sep)
```

- [ ] **Step 4: Реалізувати `points_text` і зареєструвати фільтр**

У кінець `app/i18n_plurals.py`:

```python
def points_text(value, lang=None):
    """Бали у записі активної локалі: 7,5 для uk/ru, 7.5 для en."""
    from app.utils import format_points

    lang = lang or _active_language()
    return format_points(value, sep='.' if lang == 'en' else ',')
```

У `app/__init__.py` поряд з рядком `app.jinja_env.filters['plural'] = plural` (зараз 217) додати:

```python
    app.jinja_env.filters['points'] = points_text
```

і внести `points_text` до наявного імпорту з `app.i18n_plurals`.

- [ ] **Step 5: Прогнати тест**

Run: `python -m pytest tests/test_services/test_points_format.py -v`
Expected: PASS (9 тестів)

- [ ] **Step 6: Коміт**

```bash
git add app/utils.py app/i18n_plurals.py app/__init__.py tests/test_services/test_points_format.py
git commit -m "feat(bpr): спільний розбір і показ дробових балів БПР

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Дробова форма множини

`plural()` робить `int(n)`, тож 4,5 стає четвіркою і сторінка пише «4,5 бали БПР». Українська норма -- «4,5 бала»: родовий однини, четверта форма.

**Files:**
- Modify: `app/i18n_plurals.py:16-30` (набори `bpr_points`, `points`), `app/i18n_plurals.py:86` (функція `plural`)
- Modify: `app/utils.py:162` (`uk_plural`)
- Test: `tests/test_i18n/test_plurals.py` (доповнити)

**Interfaces:**
- Consumes: нічого з Task 1.
- Produces:
  - `plural(n, key, lang=None)` -- для нецілого `n` віддає `forms[3]`, якщо вона є, інакше `forms[-1]`.
  - `uk_plural(n, one, few, many, fraction=None)` -- для нецілого `n` віддає `fraction`, якщо переданий, інакше `many`.

- [ ] **Step 1: Написати падаючий тест**

Дописати в `tests/test_i18n/test_plurals.py`:

```python
from decimal import Decimal

from app.i18n_plurals import plural
from app.utils import uk_plural


def test_plural_fraction_uses_genitive_singular():
    assert plural(Decimal('4.5'), 'bpr_points', lang='uk') == 'бала'
    assert plural(Decimal('7.5'), 'points', lang='uk') == 'бала'
    assert plural(Decimal('4.5'), 'bpr_points', lang='ru') == 'балла'


def test_plural_whole_numbers_unchanged():
    assert plural(1, 'bpr_points', lang='uk') == 'бал БПР'
    assert plural(3, 'bpr_points', lang='uk') == 'бали БПР'
    assert plural(9, 'bpr_points', lang='uk') == 'балів БПР'


def test_plural_fraction_in_two_form_language():
    assert plural(Decimal('7.5'), 'bpr_points', lang='en') == 'BPR points'


def test_plural_fraction_without_fourth_form_falls_back_to_many():
    assert plural(Decimal('2.5'), 'seats', lang='uk') == 'місць'


def test_uk_plural_fraction():
    assert uk_plural(Decimal('4.5'), 'бал', 'бали', 'балів', 'бала') == 'бала'
    assert uk_plural(Decimal('4.5'), 'бал', 'бали', 'балів') == 'балів'
    assert uk_plural(2, 'бал', 'бали', 'балів', 'бала') == 'бали'
```

- [ ] **Step 2: Прогнати тест і переконатись, що падає**

Run: `python -m pytest tests/test_i18n/test_plurals.py -v`
Expected: FAIL -- `plural(Decimal('4.5'), 'bpr_points', lang='uk')` віддає `'бали БПР'`

- [ ] **Step 3: Додати четверту форму і правило вибору**

У `app/i18n_plurals.py` доповнити два набори (порядок форм стає one/few/many/fraction):

```python
    'bpr_points': {
        'uk': ('бал БПР', 'бали БПР', 'балів БПР', 'бала БПР'),
        'ru': ('балл БПР', 'балла БПР', 'баллов БПР', 'балла БПР'),
        'en': ('BPR point', 'BPR points'),
    },
    'points': {
        'uk': ('бал', 'бали', 'балів', 'бала'),
        'ru': ('балл', 'балла', 'баллов', 'балла'),
        'en': ('point', 'points'),
    },
```

У `plural()` замінити блок приведення до `int` на:

```python
    # Дробові бали БПР (4,5) мають власну форму -- родовий однини
    # («4,5 бала»). Слов'янське правило її не дає, бо працює із залишками
    # цілого; тому нецілі відсікаємо ДО int().
    try:
        number = abs(float(n))
    except (TypeError, ValueError):
        return forms[-1]
    if number != int(number):
        return forms[3] if len(forms) > 3 else forms[-1]
    n = int(number)
    if len(forms) == 2:  # 2-формні мови (en): one / other
        return forms[0] if n == 1 else forms[1]
    return forms[_slavic_index(n)]
```

- [ ] **Step 4: Додати четвертий аргумент до `uk_plural`**

У `app/utils.py` замінити сигнатуру й тіло:

```python
def uk_plural(n, one, few, many, fraction=None):
    """Українська плюралізація: uk_plural(2, 'блок', 'блоки', 'блоків') -> 'блоки'.

    1 -> one, 2-4 -> few, 5-20/0 -> many (з урахуванням 11-14 та складених
    числівників: 21 -> one, 22 -> few, 25 -> many). Неціле -> fraction
    («4,5 бала»), а без нього -- many, щоб виклики без дробів не мінялись.
    """
    try:
        number = abs(float(n))
    except (TypeError, ValueError):
        return many
    if number != int(number):
        return fraction or many
    n = int(number)
    mod10, mod100 = n % 10, n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 10 <= mod100 < 20:
        return few
    return many
```

- [ ] **Step 5: Прогнати тести**

Run: `python -m pytest tests/test_i18n/test_plurals.py -v`
Expected: PASS

- [ ] **Step 6: Коміт**

```bash
git add app/i18n_plurals.py app/utils.py tests/test_i18n/test_plurals.py
git commit -m "feat(i18n): форма множини для дробових балів БПР

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Колонки й методи моделей

Нові колонки з'являються ПОРУЧ зі старою `cpd_points`, а властивість `effective_cpd_points` лишається тимчасово -- інакше все впаде до Task 9. Прибирає їх Task 10.

Фінальне ім'я методу -- `effective_cpd_for(fmt)`, а не `effective_cpd_points(fmt)` зі спеки: одне ім'я не може бути водночас властивістю (перехідною) і методом.

**Files:**
- Modify: `app/models/course.py:47,63,104-115`
- Modify: `app/models/course_instance.py:31,70-80,204-210`
- Modify: `app/models/registration.py:96,196-200`
- Modify: `app/models/certificate.py:45`, `app/models/lecturer_certificate.py:45`, `app/models/online_course.py:77`
- Test: `tests/test_models/test_course_instance.py` (доповнити), `tests/test_models/test_bpr_points.py` (створити)

**Interfaces:**
- Consumes: нічого.
- Produces:
  - `Course.cpd_points_online`, `Course.cpd_points_offline` -- `Numeric(5,2)`, nullable.
  - `CourseInstance.effective_cpd_for(fmt) -> Decimal | None`, де `fmt` -- `'online'` або `'offline'`; відкат на курс, якщо у проведення порожньо.
  - `CourseInstance.cpd_pairs -> list[tuple[str, Decimal]]` -- лише формати, які захід має, і лише заповнені.
  - `CourseInstance.cpd_range -> tuple[Decimal | None, Decimal | None]`.
  - `EventRegistration.participation_format` -- колонка `String(20)`.
  - `EventRegistration.effective_participation_format -> str` -- `'online'` або `'offline'`, ніколи None.
  - `EventRegistration.due_cpd_points -> Decimal | None`.

- [ ] **Step 1: Написати падаючий тест**

Створити `tests/test_models/test_bpr_points.py`:

```python
from decimal import Decimal

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.registration import EventRegistration


def _course(**kw):
    course = Course(title='Курс', slug=f'c-{id(kw)}', **kw)
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, **kw):
    inst = CourseInstance(course_id=course.id, **kw)
    db.session.add(inst)
    db.session.flush()
    return inst


def test_effective_cpd_for_takes_instance_value(app):
    course = _course(cpd_points_online=Decimal('5'), cpd_points_offline=Decimal('6'))
    inst = _instance(course, event_format='hybrid',
                     cpd_points_online=Decimal('7.5'),
                     cpd_points_offline=Decimal('9'))
    assert inst.effective_cpd_for('online') == Decimal('7.5')
    assert inst.effective_cpd_for('offline') == Decimal('9')


def test_effective_cpd_for_falls_back_to_course_per_format(app):
    course = _course(cpd_points_online=Decimal('5'), cpd_points_offline=Decimal('6'))
    inst = _instance(course, event_format='hybrid', cpd_points_online=Decimal('7.5'))
    assert inst.effective_cpd_for('online') == Decimal('7.5')
    # Порожнє офлайнове НЕ підміняється онлайновим -- відкат тільки на курс.
    assert inst.effective_cpd_for('offline') == Decimal('6')


def test_effective_cpd_for_empty_everywhere_is_none(app):
    course = _course()
    inst = _instance(course, event_format='online')
    assert inst.effective_cpd_for('online') is None


def test_cpd_pairs_only_formats_the_event_has(app):
    course = _course()
    inst = _instance(course, event_format='online',
                     cpd_points_online=Decimal('7.5'),
                     cpd_points_offline=Decimal('9'))
    assert inst.cpd_pairs == [('online', Decimal('7.5'))]


def test_cpd_pairs_hybrid_gives_both(app):
    course = _course()
    inst = _instance(course, event_format='hybrid',
                     cpd_points_online=Decimal('7.5'),
                     cpd_points_offline=Decimal('9'))
    assert inst.cpd_pairs == [('online', Decimal('7.5')), ('offline', Decimal('9'))]


def test_cpd_range(app):
    course = _course()
    inst = _instance(course, event_format='hybrid',
                     cpd_points_online=Decimal('7.5'),
                     cpd_points_offline=Decimal('9'))
    assert inst.cpd_range == (Decimal('7.5'), Decimal('9'))


def test_participation_format_prefers_own_column(app):
    course = _course()
    inst = _instance(course, event_format='hybrid')
    tariff = InstanceTariff(instance_id=inst.id, name='Онлайн',
                            price=Decimal('100'), event_format='online')
    db.session.add(tariff)
    db.session.flush()
    reg = EventRegistration(instance_id=inst.id, tariff_id=tariff.id,
                            participation_format='offline')
    db.session.add(reg)
    db.session.flush()
    assert reg.effective_participation_format == 'offline'


def test_participation_format_falls_back_to_tariff(app):
    course = _course()
    inst = _instance(course, event_format='hybrid')
    tariff = InstanceTariff(instance_id=inst.id, name='Онлайн',
                            price=Decimal('100'), event_format='online')
    db.session.add(tariff)
    db.session.flush()
    reg = EventRegistration(instance_id=inst.id, tariff_id=tariff.id)
    db.session.add(reg)
    db.session.flush()
    assert reg.effective_participation_format == 'online'


def test_participation_format_hybrid_without_tariff_is_offline(app):
    course = _course()
    inst = _instance(course, event_format='hybrid')
    reg = EventRegistration(instance_id=inst.id)
    db.session.add(reg)
    db.session.flush()
    assert reg.effective_participation_format == 'offline'


def test_participation_format_online_event_without_tariff(app):
    course = _course()
    inst = _instance(course, event_format='online')
    reg = EventRegistration(instance_id=inst.id)
    db.session.add(reg)
    db.session.flush()
    assert reg.effective_participation_format == 'online'


def test_due_cpd_points_uses_participant_format(app):
    course = _course()
    inst = _instance(course, event_format='hybrid',
                     cpd_points_online=Decimal('7.5'),
                     cpd_points_offline=Decimal('9'))
    reg = EventRegistration(instance_id=inst.id, participation_format='online')
    db.session.add(reg)
    db.session.flush()
    assert reg.due_cpd_points == Decimal('7.5')
```

- [ ] **Step 2: Прогнати тест і переконатись, що падає**

Run: `python -m pytest tests/test_models/test_bpr_points.py -v`
Expected: FAIL -- `TypeError: 'cpd_points_online' is an invalid keyword argument for Course`

- [ ] **Step 3: Додати колонки**

`app/models/course.py` -- замінити рядок `cpd_points = db.Column(db.Integer)` на:

```python
    # Бали БПР окремо за форматом участі: на гібридному заході онлайн і очно
    # дають різну кількість. Дробові (Numeric), бо 4,5 і 7,5 -- норма.
    # ТИМЧАСОВО поруч лишається cpd_points -- прибирається в Task 10.
    cpd_points = db.Column(db.Integer)
    cpd_points_online = db.Column(db.Numeric(5, 2))
    cpd_points_offline = db.Column(db.Numeric(5, 2))
```

там же `bpr_lecturer_points = db.Column(db.Integer)` -> `db.Numeric(5, 2)`.

У `__table_args__` додати поруч із наявним `ck_courses_cpd_points_non_negative`:

```python
        db.CheckConstraint(
            'cpd_points_online >= 0 OR cpd_points_online IS NULL',
            name='ck_courses_cpd_points_online_non_negative',
        ),
        db.CheckConstraint(
            'cpd_points_offline >= 0 OR cpd_points_offline IS NULL',
            name='ck_courses_cpd_points_offline_non_negative',
        ),
```

`app/models/course_instance.py` -- те саме для трійки колонок і два аналогічні констрейнти з іменами `ck_course_instances_cpd_points_online_non_negative` / `..._offline_...`.

`app/models/registration.py` -- `cpd_points_awarded = db.Column(db.Numeric(5, 2))` і поруч:

```python
    # Формат участі саме цієї людини. На гібридному заході від нього залежать
    # бали. Заповнюється з тарифу при реєстрації, але лишається окремою
    # колонкою: tariff_id буває NULL (xlsx-імпорт, заведення рукою адміна), і
    # без власного поля такий випадок не виправити.
    participation_format = db.Column(db.String(20))
```

та констрейнт:

```python
        db.CheckConstraint(
            "participation_format IN ('online', 'offline') "
            "OR participation_format IS NULL",
            name='ck_event_registrations_participation_format',
        ),
```

`app/models/certificate.py:45`, `app/models/lecturer_certificate.py:45`, `app/models/online_course.py:77` -- `db.Integer` -> `db.Numeric(5, 2)`.

- [ ] **Step 4: Додати методи**

`app/models/course_instance.py`, поряд із наявною властивістю `effective_cpd_points` (її НЕ чіпаємо до Task 10):

```python
    def effective_cpd_for(self, fmt):
        """Бали БПР для формату участі `fmt` ('online' / 'offline').

        Відкат -- лише на однойменне поле курсу. Підставляти сюди значення
        іншого формату не можна: порожній онлайн на гібриді означає «ще не
        вирішили», а не «стільки ж, скільки очно».
        """
        column = 'cpd_points_online' if fmt == 'online' else 'cpd_points_offline'
        own = getattr(self, column)
        if own is not None:
            return own
        if self.course is None:
            self._warn_orphan(column)
            return None
        return getattr(self.course, column)

    @property
    def cpd_formats(self):
        """Формати участі, які цей захід реально пропонує."""
        if self.event_format == 'hybrid':
            return ('online', 'offline')
        return (self.event_format or 'offline',)

    @property
    def cpd_pairs(self):
        """[(формат, бали)] -- лише наявні формати й лише заповнені бали."""
        pairs = []
        for fmt in self.cpd_formats:
            points = self.effective_cpd_for(fmt)
            if points is not None:
                pairs.append((fmt, points))
        return pairs

    @property
    def cpd_range(self):
        """(мінімум, максимум) балів заходу -- для вузьких місць верстки."""
        values = [points for _, points in self.cpd_pairs]
        if not values:
            return (None, None)
        return (min(values), max(values))
```

`app/models/registration.py`:

```python
    @property
    def effective_participation_format(self):
        """Формат участі: власне поле -> тариф -> формат заходу.

        Гібрид без тарифу трактуємо як очну участь -- тією ж консервативною
        логікою, що InstanceTariff.requires_attendance_confirmation.
        """
        if self.participation_format in ('online', 'offline'):
            return self.participation_format
        tariff_format = self.tariff.event_format if self.tariff else None
        if tariff_format in ('online', 'offline'):
            return tariff_format
        event_format = self.instance.event_format if self.instance else None
        return 'online' if event_format == 'online' else 'offline'

    @property
    def due_cpd_points(self):
        """Скільки балів належить саме цій людині за її форматом участі."""
        if self.instance is None:
            return None
        return self.instance.effective_cpd_for(self.effective_participation_format)
```

- [ ] **Step 5: Прогнати тести**

Run: `python -m pytest tests/test_models/test_bpr_points.py tests/test_models/test_course_instance.py tests/test_db/test_constraints.py -v`
Expected: PASS

- [ ] **Step 6: Прогнати весь набір -- він має лишитись зеленим**

Run: `python -m pytest -q`
Expected: PASS (стара `cpd_points` і властивість `effective_cpd_points` ще на місці)

- [ ] **Step 7: Коміт**

```bash
git add app/models tests/test_models/test_bpr_points.py
git commit -m "feat(bpr): колонки балів за форматом і формат участі на реєстрації

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Введення дробових в адмінці

`IntegerField`/`DecimalField` WTForms рендерять `<input type="number">`, і поле з комою браузер вважає порожнім ще до сабміту. Тому потрібен свій клас поля.

**Files:**
- Create: `app/admin/fields.py`
- Create: `app/static/js/admin-instance-points.js`
- Modify: `app/admin/forms.py:550,734,1149`
- Modify: `app/services/course_service.py:376,450,581`
- Modify: `app/templates/admin/course_edit.html:136-140,159-163`
- Modify: `app/templates/admin/instance_edit.html:126-129` і кінець файлу
- Test: `tests/test_routes/test_admin_points_fields.py` (створити)

**Interfaces:**
- Consumes: `app.utils.parse_points`, `app.utils.format_points` (Task 1); колонки з Task 3.
- Produces:
  - `app.admin.fields.PointsField` -- WTForms-поле дробових балів.
  - `CourseForm.cpd_points_online`, `CourseForm.cpd_points_offline`, `CourseInstanceForm.cpd_points_online`, `CourseInstanceForm.cpd_points_offline`, `ParticipantForm.participation_format`.

- [ ] **Step 1: Написати падаючий тест**

Створити `tests/test_routes/test_admin_points_fields.py`:

```python
from decimal import Decimal

from app.admin.fields import PointsField


class _Form:
    pass


def test_points_field_parses_comma(app):
    with app.test_request_context('/'):
        field = PointsField()
        field = field.bind(form=_Form(), name='cpd')
        field.process_formdata(['4,5'])
        assert field.data == Decimal('4.50')


def test_points_field_parses_dot(app):
    with app.test_request_context('/'):
        field = PointsField().bind(form=_Form(), name='cpd')
        field.process_formdata(['4.5'])
        assert field.data == Decimal('4.50')


def test_points_field_renders_without_trailing_zeros(app):
    with app.test_request_context('/'):
        field = PointsField().bind(form=_Form(), name='cpd')
        field.process_data(Decimal('9.00'))
        assert field._value() == '9'
        field.process_data(Decimal('7.50'))
        assert field._value() == '7,5'


def test_points_field_renders_text_input(app):
    with app.test_request_context('/'):
        field = PointsField(label='Бали').bind(form=_Form(), name='cpd')
        field.process_data(Decimal('7.50'))
        markup = str(field())
        assert 'type="text"' in markup
        assert 'inputmode="decimal"' in markup
```

- [ ] **Step 2: Прогнати тест і переконатись, що падає**

Run: `python -m pytest tests/test_routes/test_admin_points_fields.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'app.admin.fields'`

- [ ] **Step 3: Створити `PointsField`**

`app/admin/fields.py`:

```python
"""Кастомні WTForms-поля адмінки."""
from wtforms import DecimalField
from wtforms.widgets import TextInput

from app.utils import format_points, parse_points


class PointsField(DecimalField):
    """Дробові бали БПР з комою або крапкою на вводі.

    Віджет саме текстовий: <input type="number"> у браузері не приймає кому,
    і поле «4,5» доходить до сервера порожнім ще до будь-якої валідації.
    """

    widget = TextInput()

    def __init__(self, *args, **kwargs):
        render_kw = dict(kwargs.pop('render_kw', None) or {})
        render_kw.setdefault('inputmode', 'decimal')
        super().__init__(*args, render_kw=render_kw, **kwargs)

    def process_formdata(self, valuelist):
        if not valuelist:
            return
        try:
            self.data = parse_points(valuelist[0])
        except ValueError:
            self.data = None
            raise ValueError(self.gettext('Введіть число, напр. 4,5'))

    def _value(self):
        if self.raw_data:
            return self.raw_data[0]
        return format_points(self.data)
```

- [ ] **Step 4: Перевести поля форм**

У `app/admin/forms.py` додати імпорт `from app.admin.fields import PointsField` і замінити:

- `CourseForm.cpd_points` (рядок 550) на пару:

```python
    cpd_points_online = PointsField(
        'Бали БПР онлайн (default)',
        validators=[Optional(), NumberRange(min=0)],
    )
    cpd_points_offline = PointsField(
        'Бали БПР офлайн (default)',
        validators=[Optional(), NumberRange(min=0)],
    )
```

- `CourseForm.bpr_lecturer_points` -- `IntegerField` на `PointsField` (валідатори без змін);
- `CourseInstanceForm.cpd_points` (рядок 734) на пару з тими самими підписами без «(default)» і `description='Залиште порожнім щоб взяти з курсу'`;
- `ParticipantForm.cpd_points_awarded` (рядок 1149) -- `IntegerField` на `PointsField`;
- у `ParticipantForm` додати:

```python
    participation_format = SelectField(
        'Формат участі',
        choices=[('', 'За тарифом'), ('online', 'Онлайн'), ('offline', 'Офлайн')],
        validators=[Optional()],
        description='Впливає на кількість балів БПР на гібридному заході.',
    )
```

- [ ] **Step 5: Перевести збереження**

`app/services/course_service.py`:

- рядок 376: `course.cpd_points = form.cpd_points.data` ->

```python
    course.cpd_points_online = form.cpd_points_online.data
    course.cpd_points_offline = form.cpd_points_offline.data
```

- рядок 450: те саме для `instance`;
- рядок 581 (клон курсу): `cpd_points=source.cpd_points,` ->

```python
        cpd_points_online=source.cpd_points_online,
        cpd_points_offline=source.cpd_points_offline,
```

- [ ] **Step 6: Оновити шаблони**

`app/templates/admin/course_edit.html` -- блок `cpd_points` замінити на два:

```html
        <div class="form-group">
          <label for="cpd_points_online">Бали БПР онлайн (default)</label>
          {{ form.cpd_points_online(class="form-input", id="cpd_points_online", placeholder="7,5") }}
        </div>

        <div class="form-group">
          <label for="cpd_points_offline">Бали БПР офлайн (default)</label>
          {{ form.cpd_points_offline(class="form-input", id="cpd_points_offline", placeholder="9") }}
        </div>
```

У блоці `bpr_lecturer_points` підказку доповнити реченням `Приймається дробове значення (4,5).`

`app/templates/admin/instance_edit.html` -- блок `cpd_points` замінити на:

```html
        <div class="form-group" data-cpd-format="online">
          <label for="cpd_points_online">Бали БПР онлайн</label>
          {{ form.cpd_points_online(class="form-input", id="cpd_points_online", placeholder="7,5") }}
          <small class="form-hint">{{ form.cpd_points_online.description }}</small>
        </div>

        <div class="form-group" data-cpd-format="offline">
          <label for="cpd_points_offline">Бали БПР офлайн</label>
          {{ form.cpd_points_offline(class="form-input", id="cpd_points_offline", placeholder="9") }}
          <small class="form-hint">{{ form.cpd_points_offline.description }}</small>
        </div>
```

і перед `{% endblock %}` наприкінці файлу:

```html
<script src="{{ url_for('static', filename='js/admin-instance-points.js') }}?v={{ assets_version }}"></script>
```

- [ ] **Step 7: Написати перемикач видимості**

`app/static/js/admin-instance-points.js`:

```javascript
(function () {
  // Формат заходу вирішує, яке з двох полів балів має сенс. Приховане поле
  // лишається в DOM і далі сабмітить своє значення: перемикання формату не
  // повинно мовчки стирати бали, бо захід нерідко стає гібридним пізніше.
  var select = document.getElementById('event_format');
  var groups = document.querySelectorAll('[data-cpd-format]');
  if (!select || !groups.length) return;

  function sync() {
    var format = select.value;
    for (var i = 0; i < groups.length; i++) {
      var wanted = groups[i].getAttribute('data-cpd-format');
      groups[i].hidden = !(format === 'hybrid' || format === wanted);
    }
  }

  select.addEventListener('change', sync);
  sync();
})();
```

- [ ] **Step 8: Прогнати тести**

Run: `python -m pytest tests/test_routes/test_admin_points_fields.py tests/test_routes -q`
Expected: PASS

- [ ] **Step 9: Коміт**

```bash
git add app/admin/fields.py app/admin/forms.py app/services/course_service.py app/templates/admin/course_edit.html app/templates/admin/instance_edit.html app/static/js/admin-instance-points.js tests/test_routes/test_admin_points_fields.py
git commit -m "feat(admin): дробові бали БПР і два поля за форматом у редакторах

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Показ балів на публічних сторінках

Один макрос замість восьми самостійних `{% if %}`.

**Files:**
- Create: `app/templates/partials/_bpr_points.html`
- Modify: `app/templates/courses/detail.html:64,185`, `app/templates/courses/list.html:165-166`, `app/templates/partials/_course_card.html:9-11,75-81`, `app/templates/partials/_course_recommend_card.html:34-36,64-70`, `app/templates/partials/_course_schedule.html:27`, `app/templates/auth/account.html:95-100`, `app/templates/registration/register.html:55-56`, `app/templates/registration/complete.html:49`, `app/templates/registration/confirmation.html:219-227`
- Modify: `app/registration/routes.py:58`, `app/courses/routes.py:144`, `app/static/js/page-courses-schedule.js:258`
- Test: `tests/test_routes/test_bpr_points_display.py` (створити)

**Interfaces:**
- Consumes: `cpd_pairs`, `cpd_range` (Task 3); фільтри `points`, `plural` (Tasks 1-2).
- Produces:
  - макроси `points_by_format(pairs)` і `points_range(low, high)` у `partials/_bpr_points.html`;
  - `_EventShape.cpd_pairs`, `_EventShape.cpd_range` у `app/registration/routes.py`;
  - ключ `cpd_text` (готовий локалізований рядок) замість `cpd` у `_serialize_event`.

- [ ] **Step 1: Написати падаючий тест**

Створити `tests/test_routes/test_bpr_points_display.py`:

```python
from decimal import Decimal

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance


def _published_hybrid(app):
    course = Course(title='Гібрид', slug='hybrid-bpr', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, event_format='hybrid', status='published',
        cpd_points_online=Decimal('7.50'), cpd_points_offline=Decimal('9.00'),
    )
    db.session.add(inst)
    db.session.commit()
    return course, inst


def test_course_page_shows_both_formats(client, app):
    course, _ = _published_hybrid(app)
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert '7,5' in html
    assert '9' in html
    assert '7.50' not in html


def test_schedule_tag_shows_range(client, app):
    _published_hybrid(app)
    html = client.get('/courses').get_data(as_text=True)
    assert '7,5' in html and '9' in html
```

- [ ] **Step 2: Прогнати тест і переконатись, що падає**

Run: `python -m pytest tests/test_routes/test_bpr_points_display.py -v`
Expected: FAIL -- сторінка показує `7.50` або не показує онлайнового значення

- [ ] **Step 3: Написати макрос**

`app/templates/partials/_bpr_points.html`:

```html
{# Єдине місце, де вирішується, як показати бали БПР. Захід буває
   гібридний, і тоді значень два -- широкі блоки друкують обидва з
   підписами, вузькі (теги, картки) -- діапазон. #}

{% macro points_by_format(pairs) %}
  {%- if pairs | length == 1 -%}
    {{ pairs[0][1] | points }} {{ pairs[0][1] | plural('bpr_points') }}
  {%- elif pairs | length > 1 -%}
    {%- set values = pairs | map(attribute=1) | list -%}
    {%- if values | unique | list | length == 1 -%}
      {{ values[0] | points }} {{ values[0] | plural('bpr_points') }}
    {%- else -%}
      {%- for fmt, value in pairs -%}
        {%- if not loop.first %} &middot; {% endif -%}
        {{ _('Онлайн') if fmt == 'online' else _('Офлайн') }} {{ value | points }}
      {%- endfor %} {{ values | max | plural('bpr_points') }}
    {%- endif -%}
  {%- endif -%}
{% endmacro %}

{% macro points_range(low, high) %}
  {%- if low and high and high != low -%}
    {{ low | points }}&ndash;{{ high | points }} {{ high | plural('bpr_points') }}
  {%- elif low -%}
    {{ low | points }} {{ low | plural('bpr_points') }}
  {%- endif -%}
{% endmacro %}
```

- [ ] **Step 4: Перевести шаблони**

У кожному з файлів на початку додати `{% from 'partials/_bpr_points.html' import points_by_format, points_range %}` і замінити виведення:

- `courses/detail.html:185` -- `hero_meta.append({'value': ..., 'label': ...})` більше не годиться для пари, тому чип збирається окремим рядком під hero через `points_by_format(inst.cpd_pairs)` для показаного проведення; рядок 64 (`numberOfCredits`) бере `course.cpd_points_offline or course.cpd_points_online` і віддає `| float`;
- `courses/list.html:166` і `partials/_course_schedule.html:27` -- `{{ points_range(*inst.cpd_range) }}`;
- `partials/_course_card.html:9-11` -- замінити збір `_cpds` на:

```html
{% set _ranges = insts | map(attribute='cpd_range') | list %}
{% set _lows = _ranges | map(attribute=0) | reject('none') | list %}
{% set _highs = _ranges | map(attribute=1) | reject('none') | list %}
{% set cpd_min = _lows | min if _lows else (course.cpd_points_online or course.cpd_points_offline) %}
{% set cpd_max = _highs | max if _highs else (course.cpd_points_offline or course.cpd_points_online) %}
```

а блок 75-81 -- на `{{ points_range(cpd_min, cpd_max) }}`; те саме для `_course_recommend_card.html`;
- `auth/account.html:95-96` -- `{{ points_range(*reg.instance.cpd_range) }}`, рядок 100 -- `{{ reg.cpd_points_awarded | points }}`;
- `registration/register.html`, `complete.html`, `confirmation.html` -- `{{ points_by_format(event.cpd_pairs) }}`, а нараховані бали -- `{{ reg.cpd_points_awarded | points }}`.

- [ ] **Step 5: Оновити серіалізацію для сторінки реєстрації та розкладу**

`app/registration/routes.py:58` -- замість `self.cpd_points = instance.effective_cpd_points`:

```python
        self.cpd_pairs = instance.cpd_pairs
        self.cpd_range = instance.cpd_range
```

`app/courses/routes.py:144` -- замість `'cpd': inst.effective_cpd_points`:

```python
        # Готовий локалізований рядок, а не число: інакше плюралізацію й
        # роздільник довелося б повторювати в JS, і вони розійшлися б.
        'cpd_text': render_template(
            'partials/_bpr_points_text.html', pairs=inst.cpd_pairs,
        ).strip(),
```

де `app/templates/partials/_bpr_points_text.html` -- однорядковий шаблон:

```html
{% from 'partials/_bpr_points.html' import points_by_format %}{{ points_by_format(pairs) }}
```

`app/static/js/page-courses-schedule.js:258` -- замінити рядок на:

```javascript
    if (ev.cpd_text) meta.push(escapeHtml(ev.cpd_text));
```

- [ ] **Step 6: Прогнати тести**

Run: `python -m pytest tests/test_routes/test_bpr_points_display.py tests/test_routes/test_course_detail_layout.py tests/test_routes/test_course_recommend.py tests/test_design_system -q`
Expected: PASS

- [ ] **Step 7: Коміт**

```bash
git add app/templates app/registration/routes.py app/courses/routes.py app/static/js/page-courses-schedule.js tests/test_routes/test_bpr_points_display.py
git commit -m "feat(courses): показ балів БПР за форматом участі

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Нарахування балів за форматом учасника

**Files:**
- Modify: `app/services/quiz_service.py:207,234,733`
- Modify: `app/admin/routes_registrations.py:281-296`
- Modify: `app/templates/admin/partials/_registration_actions.html:69`
- Modify: `app/admin/routes_participants.py:96,310`, `app/services/participant_service.py:201`
- Modify: `app/templates/admin/participant_edit.html:188-192`
- Modify: `app/registration/routes.py` (створення реєстрації в чекауті)
- Modify: `app/services/email_service.py:494`
- Test: `tests/test_routes/test_quiz.py` (доповнити), `tests/test_services/test_award_points.py` (створити)

**Interfaces:**
- Consumes: `due_cpd_points`, `effective_participation_format` (Task 3); `parse_points` (Task 1); `ParticipantForm.participation_format` (Task 4).
- Produces: нічого нового назовні.

- [ ] **Step 1: Написати падаючий тест**

Створити `tests/test_services/test_award_points.py`:

```python
from decimal import Decimal

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.services import quiz_service


def _hybrid_registration(participation_format):
    course = Course(title='Гібрид', slug=f'award-{participation_format}')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, event_format='hybrid', status='active',
        cpd_points_online=Decimal('7.50'), cpd_points_offline=Decimal('9.00'),
    )
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        instance_id=inst.id, participation_format=participation_format,
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def test_award_gives_online_points_to_online_participant(app):
    reg = _hybrid_registration('online')
    quiz_service.award_and_issue(reg)
    assert reg.cpd_points_awarded == Decimal('7.50')


def test_award_gives_offline_points_to_offline_participant(app):
    reg = _hybrid_registration('offline')
    quiz_service.award_and_issue(reg)
    assert reg.cpd_points_awarded == Decimal('9.00')


def test_gate_blocks_online_participant_when_only_offline_filled(app):
    reg = _hybrid_registration('online')
    reg.instance.cpd_points_online = None
    db.session.commit()
    assert quiz_service._bpr_is_configured(
        reg.instance, registration=reg,
    ) is False


def test_gate_allows_offline_participant_when_only_offline_filled(app):
    reg = _hybrid_registration('offline')
    reg.instance.cpd_points_online = None
    db.session.commit()
    assert quiz_service._bpr_is_configured(
        reg.instance, registration=reg,
    ) is True
```

Гейт перевіряємо напряму, а не через `eligibility`: та вимагає ще й
номера провайдера, номера заходу БПР, готового тесту й заповненого
медичного профілю, тож її падіння не сказало б, чи спрацювали саме бали.

- [ ] **Step 2: Прогнати тест і переконатись, що падає**

Run: `python -m pytest tests/test_services/test_award_points.py -v`
Expected: FAIL -- онлайновий учасник отримує 9.00 (`effective_cpd_points` повертає офлайнове значення)

- [ ] **Step 3: Перевести автовидачу і гейти**

`app/services/quiz_service.py`:

- рядок 733 -- `instance.effective_cpd_points if instance else None` -> `registration.due_cpd_points`;
- рядок 234 (`_bpr_is_configured`) -- сигнатура стає `_bpr_is_configured(instance, context=None, registration=None)`, а останній рядок:

```python
    # Бали друкуються на сертифікаті; без них документ виходить порожнім.
    # Перевіряємо саме формат цієї людини: на гібриді із заповненим лише
    # офлайном онлайновий учасник мусить упертися сюди, а не отримати
    # сертифікат із порожнім місцем під бали.
    if registration is not None:
        return bool(registration.due_cpd_points)
    return any(instance.effective_cpd_for(fmt) for fmt in instance.cpd_formats)
```

- рядок 358 -- виклик стає `_bpr_is_configured(instance, context, registration)`;
- рядок 207 (тизер на сторінці курсу, реєстрації немає) -- `not course.cpd_points` -> `not (course.cpd_points_online or course.cpd_points_offline)`.

- [ ] **Step 4: Перевести ручне підтвердження присутності**

`app/admin/routes_registrations.py:281-288`:

```python
    try:
        cpd = parse_points(request.form.get('cpd_points'))
    except ValueError:
        flash('Некоректна кількість балів БПР', 'error')
        return _redirect_after_action(reg)
    # max cap = 2x належних цій людині балів (або принаймні 100)
    base_cpd = reg.due_cpd_points
    max_cpd = (base_cpd or 0) * 2
    if cpd is not None and (cpd < 0 or cpd > max(max_cpd, 100)):
        flash('Некоректна кількість балів БПР', 'error')
        return _redirect_after_action(reg)
    reg.cpd_points_awarded = cpd if cpd is not None else base_cpd
```

плюс імпорт `from app.utils import format_points, parse_points` і flash-рядок через `format_points(reg.cpd_points_awarded)`.

`app/templates/admin/partials/_registration_actions.html:69`:

```html
      <input type="hidden" name="cpd_points" value="{{ reg.due_cpd_points | points }}">
```

- [ ] **Step 5: Провести формат участі крізь картку учасника і чекаут**

`app/admin/routes_participants.py:96` -- додати `'participation_format': form.participation_format.data or None,`; рядок 310 (заповнення форми з моделі) -- `'participation_format': reg.participation_format or '',`.

`app/services/participant_service.py:201` -- поруч із `cpd_points_awarded`:

```python
    reg.participation_format = data.get('participation_format')
```

`app/templates/admin/participant_edit.html` -- після блоку `cpd_points_awarded` додати:

```html
        <div class="form-group">
          <label for="participation_format">Формат участі</label>
          {{ form.participation_format(class="form-input", id="participation_format") }}
          <small class="form-hint">{{ form.participation_format.description }}</small>
        </div>
```

`app/registration/routes.py` -- у місці, де створюється `EventRegistration` з обраним тарифом, додати `participation_format=tariff.event_format if tariff else None`.

- [ ] **Step 6: Перевести лист про захід**

`app/services/email_service.py:494` -- `cpd_points = instance.effective_cpd_points` -> `cpd_points = registration.due_cpd_points` (об'єкт реєстрації в цій функції вже є; якщо ні -- прокинути параметром із виклику).

- [ ] **Step 7: Прогнати тести**

Run: `python -m pytest tests/test_services/test_award_points.py tests/test_routes/test_quiz.py tests/test_routes/test_admin_quizzes.py tests/test_services/test_participant_service.py -q`
Expected: PASS

- [ ] **Step 8: Коміт**

```bash
git add app/services/quiz_service.py app/admin app/templates/admin app/registration/routes.py app/services/email_service.py app/services/participant_service.py tests/test_services/test_award_points.py
git commit -m "feat(bpr): бали нараховуються за форматом участі конкретної людини

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Сертифікати

**Files:**
- Modify: `app/services/certificate_service.py:190,237-248`
- Modify: `app/templates/certificates/certificate.html:192-194`, `app/templates/certificates/certificate_compact.html:205-207`
- Modify: `app/templates/emails/certificate_issued.html:30-32`, `app/templates/admin/certificates.html:83`, `app/templates/admin/partials/_registration_progress.html:98`, `app/templates/admin/registration_quiz.html:130`, `app/templates/quiz/done.html:26`
- Test: `tests/test_services/test_certificate_points.py` (створити)

**Interfaces:**
- Consumes: `due_cpd_points` (Task 3), `format_points` (Task 1), `uk_plural` з четвертою формою (Task 2).
- Produces: нічого нового назовні.

- [ ] **Step 1: Написати падаючий тест**

Створити `tests/test_services/test_certificate_points.py`:

```python
from decimal import Decimal

from app.services.certificate_service import points_badge_url


def test_badge_name_has_no_trailing_zeros(app, monkeypatch):
    seen = []

    def fake_exists(path):
        seen.append(path)
        return False

    monkeypatch.setattr('app.services.certificate_service.os.path.exists', fake_exists)
    with app.app_context():
        points_badge_url(Decimal('9.00'))
    assert any(p.endswith('9-points-BPR.webp') for p in seen)
    assert not any(p.endswith('9.00-points-BPR.webp') for p in seen)


def test_badge_name_keeps_fraction_with_dot(app, monkeypatch):
    seen = []
    monkeypatch.setattr(
        'app.services.certificate_service.os.path.exists',
        lambda p: seen.append(p) or False,
    )
    with app.app_context():
        points_badge_url(Decimal('7.50'))
    assert any(p.endswith('7.5-points-BPR.webp') for p in seen)
```

- [ ] **Step 2: Прогнати тест і переконатись, що падає**

Run: `python -m pytest tests/test_services/test_certificate_points.py -v`
Expected: FAIL -- шукається `9.00-points-BPR.webp`

- [ ] **Step 3: Полагодити ім'я розетки і знімок балів**

`app/services/certificate_service.py` -- у `points_badge_url` замінити збір імені:

```python
    points = cpd_points if cpd_points is not None else _POINTS_BADGE_DEFAULT
    # Ім'я збирається тим самим нормалізатором, що й показ, інакше
    # Decimal('9.00') шукає файл «9.00-points-BPR.webp», якого немає, і
    # дев'ятибальний захід тихо отримує десятибальну розетку.
    fname = f'{format_points(points, sep=".")}-points-BPR.webp'
```

плюс імпорт `from app.utils import format_points`.

Рядок 190 -- `cpd = instance.effective_cpd_points` -> `cpd = registration.due_cpd_points`.

- [ ] **Step 4: Оновити шаблони сертифіката**

`certificates/certificate.html:193` і `certificate_compact.html:206`:

```html
        <p class="cert__points-text">та отримав(-ла) <strong>{{ certificate.cpd_points | points }} {{ certificate.cpd_points | uk_plural('бал БПР', 'бали БПР', 'балів БПР', 'бала БПР') }}</strong></p>
```

Решта перелічених шаблонів: додати фільтр `| points` до кожного виведення `cpd_points` / `cpd_points_awarded`.

- [ ] **Step 5: Прогнати тести**

Run: `python -m pytest tests/test_services/test_certificate_points.py tests/test_services/test_certificate_number.py tests/test_routes/test_course_certificate_block.py -q`
Expected: PASS

- [ ] **Step 6: Коміт**

```bash
git add app/services/certificate_service.py app/templates tests/test_services/test_certificate_points.py
git commit -m "fix(certificates): дробові бали БПР у документі й у назві розетки

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Партнерське API

Ламальна зміна контракту. Перед деплоєм звіряємось із mm-medic (див. «Порядок деплою»).

**Files:**
- Modify: `app/api/v1/serializers.py:217-219,332`, `app/api/v1/clients.py:289`
- Test: `tests/test_routes/test_api_v1.py` (доповнити)

**Interfaces:**
- Consumes: `effective_cpd_for` (Task 3).
- Produces: ключі `cpd_points_online`, `cpd_points_offline` замість `cpd_points` у картці заходу.

- [ ] **Step 1: Написати падаючий тест**

Дописати в `tests/test_routes/test_api_v1.py`:

```python
@pytest.fixture
def hybrid_event(app, user):
    c = Course(
        title='Hybrid', slug=f'hyb-{_uid()}', event_type='course',
        base_price=1500, is_active=True, created_by=user.id,
    )
    db.session.add(c)
    db.session.flush()
    inst = CourseInstance(
        course_id=c.id, status='published', event_format='hybrid', price=1500,
        cpd_points_online=Decimal('7.50'), cpd_points_offline=Decimal('9.00'),
        start_date=datetime.now(timezone.utc) + timedelta(days=10),
    )
    db.session.add(inst)
    db.session.flush()
    c._test_instance = inst
    return c


def test_event_card_exposes_points_per_format(
    client, partner_settings, hybrid_event,
):
    resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
    card = next(
        item for item in resp.get_json()['items']
        if item['slug'] == hybrid_event.slug
    )
    assert 'cpd_points' not in card
    assert card['cpd_points_online'] == 7.5
    assert card['cpd_points_offline'] == 9.0
```

До імпортів файлу додати `from decimal import Decimal`.

- [ ] **Step 2: Прогнати тест і переконатись, що падає**

Run: `python -m pytest tests/test_routes/test_api_v1.py -v -k points`
Expected: FAIL -- у картці є `cpd_points`, немає нових ключів

- [ ] **Step 3: Замінити ключі**

`app/api/v1/serializers.py` -- блок `'cpd_points': (...)` замінити на:

```python
        # Розділено за форматом участі: на гібриді онлайн і очно дають різні
        # бали, і одне число тут завжди було неправдою для половини людей.
        'cpd_points_online': _points(
            instance.effective_cpd_for('online') if instance
            else course.cpd_points_online
        ),
        'cpd_points_offline': _points(
            instance.effective_cpd_for('offline') if instance
            else course.cpd_points_offline
        ),
```

і поруч із іншими приватними хелперами файлу:

```python
def _points(value):
    """Бали назовні -- числом, щоб партнеру не парсити кому."""
    return float(value) if value is not None else None
```

`serializers.py:332` (онлайн-курс) -- `'cpd_points': _points(course.cpd_points),`; білий список `ONLINE_COURSE_PUBLIC_FIELDS` не змінюється.

`app/api/v1/clients.py:289` -- `'cpd_points_awarded': _points(reg.cpd_points_awarded),`.

- [ ] **Step 4: Прогнати тести**

Run: `python -m pytest tests/test_routes/test_api_v1.py -q`
Expected: PASS

- [ ] **Step 5: Коміт**

```bash
git add app/api tests/test_routes/test_api_v1.py
git commit -m "feat(api): бали БПР у партнерському API розділено за форматом

BREAKING: ключ cpd_points у картці заходу замінено на cpd_points_online
і cpd_points_offline. Потребує зустрічної правки в mm-medic.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: XLSX-імпорт та експорт

**Files:**
- Modify: `app/services/xlsx_io.py:87-100,478-500,714,953,1093,1148,1209-1228,1300,1456,1518,1557,1576-1640,1877,2134`
- Test: `tests/test_services/test_xlsx_points.py` (створити)

**Interfaces:**
- Consumes: `parse_points` (Task 1), колонки з Task 3.
- Produces: колонки `cpd_points_online` / `cpd_points_offline` у курсах і проведеннях, `participation_format` у реєстраціях.

- [ ] **Step 1: Написати падаючий тест**

Створити `tests/test_services/test_xlsx_points.py`:

```python
from decimal import Decimal

from app.services.xlsx_io import _points_cell


def test_points_cell_accepts_comma():
    assert _points_cell('7,5') == Decimal('7.50')


def test_points_cell_accepts_dot_and_blank():
    assert _points_cell('7.5') == Decimal('7.50')
    assert _points_cell('') is None


def test_points_cell_rejects_text():
    import pytest
    with pytest.raises(ValueError):
        _points_cell('багато')
```

- [ ] **Step 2: Прогнати тест і переконатись, що падає**

Run: `python -m pytest tests/test_services/test_xlsx_points.py -v`
Expected: FAIL -- `ImportError: cannot import name '_points_cell'`

- [ ] **Step 3: Додати парсер комірки і числовий формат**

У `app/services/xlsx_io.py` поряд із `_int` (рядок 448):

```python
def _points_cell(v) -> 'Decimal | None':
    """Бали БПР із комірки: приймає і «7,5», і «7.5» (Excel з укр. локаллю)."""
    from app.utils import parse_points

    try:
        return parse_points(v)
    except ValueError:
        raise ValueError(f'некоректні бали БПР: {v!r}')
```

Поряд із `FMT_INT` додати `FMT_POINTS = '0.##'` і в `NUMBER_FORMATS` замінити ключ `'cpd_points': FMT_INT` на `'cpd_points_online': FMT_POINTS`, `'cpd_points_offline': FMT_POINTS`, а `'cpd_points_awarded': FMT_INT` -- на `FMT_POINTS`.

- [ ] **Step 4: Розщепити колонки курсів і проведень**

У `COURSE_COLS` і `INSTANCE_COLS` замінити `'cpd_points'` на `'cpd_points_online', 'cpd_points_offline'`; у `COURSE_LABELS` / `INSTANCE_LABELS` -- на `'Бали БПР онлайн'` і `'Бали БПР офлайн'`. Те саме в мапах ширин колонок і у зразкових рядках (`xlsx_io.py:183,204`).

Експорт (рядки 714 і 1300): `c.cpd_points` -> `c.cpd_points_online, c.cpd_points_offline` (два значення в тому самому порядку, що й колонки), приведені `float(...) if ... is not None else None`.

Розбір (рядки 953 і 1456): `'cpd_points': _int(...)` -> дві пари `'cpd_points_online': _points_cell(raw.get('cpd_points_online'))` і аналогічно для offline.

Списки полів застосування (рядки 1093 і 1518) і присвоєння (1148, 1557): замінити `'cpd_points'` на дві нові назви.

- [ ] **Step 5: Додати формат участі у вивантаження реєстрацій**

У `PARTICIPANT_COLS` після `'cpd_points_awarded'` додати `'participation_format'`; у `PARTICIPANT_LABELS` -- `'participation_format': 'Формат участі'`; у мапу ширин -- `'participation_format': 16`.

Рядок 1877 (експорт): після `reg.cpd_points_awarded` додати:

```python
            {'online': 'Онлайн', 'offline': 'Офлайн'}.get(
                reg.effective_participation_format, ''),
```

Рядок 2134 (імпорт): `cpd = _int(raw.get('cpd_points_awarded'))` -> `cpd = _points_cell(raw.get('cpd_points_awarded'))`.

- [ ] **Step 6: Прогнати тести**

Run: `python -m pytest tests/test_services/test_xlsx_points.py tests/test_services -q`
Expected: PASS

- [ ] **Step 7: Коміт**

```bash
git add app/services/xlsx_io.py tests/test_services/test_xlsx_points.py
git commit -m "feat(xlsx): дві колонки балів БПР і формат участі у вивантаженнях

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Прибрати стару колонку

Тепер, коли жоден споживач її не читає, зникає і колонка `cpd_points`, і перехідна властивість `effective_cpd_points`.

**Files:**
- Modify: `app/models/course.py`, `app/models/course_instance.py`
- Modify: `app/admin/routes_online_courses.py:184,222` (там своя `cpd_points` -- лишається, але переходить на `parse_points`)

**Interfaces:**
- Consumes: усе з Tasks 3-9.
- Produces: `Course.cpd_points` і `CourseInstance.cpd_points` більше не існують.

- [ ] **Step 1: Переконатись, що споживачів не лишилось**

Run: `grep -rn "effective_cpd_points\|\.cpd_points\b" app/ --include=*.py --include=*.html | grep -v online_course | grep -v certificate`
Expected: порожній вивід (окрім онлайн-курсів і сертифікатів, у яких власна однойменна колонка)

- [ ] **Step 2: Видалити колонку і властивість**

З `app/models/course.py` прибрати рядок `cpd_points = db.Column(db.Integer)` і констрейнт `ck_courses_cpd_points_non_negative`; з `app/models/course_instance.py` -- те саме плюс властивість `effective_cpd_points` цілком.

- [ ] **Step 3: Перевести онлайн-курс на спільний парсер**

`app/admin/routes_online_courses.py:184`:

```python
    try:
        cpd = parse_points(request.form.get('cpd_points'))
    except ValueError:
        return None, 'Бали БПР: введіть число, напр. 4,5'
    err = None
    if cpd is not None and cpd < 0:
        cpd, err = None, 'Бали БПР не можуть бути від\'ємними'
```

(підлаштувати під наявний контракт `_parse_positive_int`, зберігши формат повернення `(значення, помилка)`), і в `app/templates/admin/online_course_edit.html:321-323` замінити `<input type="number" ... step="1">` на `type="text" inputmode="decimal"` зі значенням `{{ course.cpd_points | points }}`.

- [ ] **Step 4: Оновити тестові фікстури, що ще ставлять стару колонку**

Run: `grep -rn "cpd_points=" tests/ --include=*.py`
Expected: знайдені місця (зокрема `tests/test_routes/test_api_v1.py:55,62`) переводяться на `cpd_points_online=` / `cpd_points_offline=` з тим самим значенням. Це не косметика: без правки колекція тестів упаде на `TypeError: 'cpd_points' is an invalid keyword argument`.

- [ ] **Step 5: Прогнати ВЕСЬ набір**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 6: Коміт**

```bash
git add app/models app/admin/routes_online_courses.py app/templates/admin/online_course_edit.html tests/
git commit -m "refactor(bpr): прибрано стару колонку cpd_points

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Міграція

Пишеться останньою: тестова база збирається `create_all()` з моделей, тож міграція жодним іншим тестом не перевіряється -- лише власним.

**Files:**
- Create: `migrations/versions/bpr_points_split_20260909_add_format_columns.py`
- Test: `tests/test_db/test_migration_bpr_points_split.py` (створити)

**Interfaces:**
- Consumes: схему з Tasks 3 і 10.
- Produces: `revision = 'bpr_points_split_20260909'`; helper `participation_format_backfill_sql()` для тесту.

- [ ] **Step 1: Дізнатись поточну голову**

Run: `flask db heads`
Expected: рівно один рядок -- його значення йде у `down_revision`

- [ ] **Step 2: Написати падаючий тест**

Створити `tests/test_db/test_migration_bpr_points_split.py`:

```python
"""Міграція bpr_points_split_20260909.

Саму upgrade() тут не проганяємо: у тестовій схемі (create_all з моделей)
нові колонки вже є, тож add_column упав би на дублікаті. Перевіряємо те, що
справді може піти не так, -- перенесення даних.
"""
import importlib.util
from pathlib import Path

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
    / 'bpr_points_split_20260909_add_format_columns.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_points_split', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_copies_old_value_into_both_columns(migration):
    for table in ('courses', 'course_instances'):
        sql = migration.copy_points_sql(table)
        assert 'cpd_points_online = cpd_points' in sql
        assert 'cpd_points_offline = cpd_points' in sql
        assert table in sql


def test_backfill_takes_format_from_tariff(migration):
    sql = migration.participation_format_backfill_sql()
    assert 'instance_tariffs' in sql
    assert 'event_format' in sql
    # Тільки задані формати: NULL у тарифі не має ставати рядком.
    assert "IN ('online', 'offline')" in sql


def test_downgrade_keeps_offline_value(migration):
    sql = migration.collapse_points_sql('courses')
    assert 'cpd_points = cpd_points_offline' in sql
```

- [ ] **Step 3: Прогнати тест і переконатись, що падає**

Run: `python -m pytest tests/test_db/test_migration_bpr_points_split.py -v`
Expected: FAIL -- файлу міграції немає

- [ ] **Step 4: Написати міграцію**

`migrations/versions/bpr_points_split_20260909_add_format_columns.py`:

```python
"""Бали БПР: дробові й окремі для онлайн- та офлайн-участі

Revision ID: bpr_points_split_20260909
Revises: <ГОЛОВА З КРОКУ 1>
Create Date: 2026-09-09

Why
---
Бали зберігались цілим числом в одній колонці на захід. Це неправда двічі:
нарахування буває дробовим (4,5 / 7,5), а на гібридному заході онлайнова й
очна участь дають РІЗНУ кількість балів, і одна колонка змушувала адміна
обрати, кого саме обманути.

Перенесення даних
-----------------
Наявне значення копіюється в ОБИДВІ нові колонки: жоден чинний захід не
міняє поведінки, а онлайнове значення адмін проставить свідомо там, де воно
інше.

participation_format бекфілиться з формату тарифу реєстрації. Де тарифу
немає (xlsx-імпорт, заведення рукою адміна) -- лишається NULL і читається
моделлю: формат заходу, а для гібрида -- офлайн.
"""
from alembic import op
import sqlalchemy as sa


revision = 'bpr_points_split_20260909'
down_revision = '<ГОЛОВА З КРОКУ 1>'
branch_labels = None
depends_on = None

POINTS_TABLES = ('courses', 'course_instances')


def copy_points_sql(table):
    return (
        f'UPDATE {table} SET cpd_points_online = cpd_points, '
        f'cpd_points_offline = cpd_points WHERE cpd_points IS NOT NULL'
    )


def collapse_points_sql(table):
    return (
        f'UPDATE {table} SET cpd_points = cpd_points_offline '
        f'WHERE cpd_points_offline IS NOT NULL'
    )


def participation_format_backfill_sql():
    return (
        "UPDATE event_registrations SET participation_format = ("
        "SELECT t.event_format FROM instance_tariffs t "
        "WHERE t.id = event_registrations.tariff_id"
        ") WHERE tariff_id IS NOT NULL AND ("
        "SELECT t.event_format FROM instance_tariffs t "
        "WHERE t.id = event_registrations.tariff_id"
        ") IN ('online', 'offline')"
    )


def upgrade():
    for table in POINTS_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('cpd_points_online', sa.Numeric(5, 2)))
            batch.add_column(sa.Column('cpd_points_offline', sa.Numeric(5, 2)))
        op.execute(copy_points_sql(table))

    with op.batch_alter_table('courses') as batch:
        batch.alter_column('bpr_lecturer_points', type_=sa.Numeric(5, 2))
        batch.drop_constraint('ck_courses_cpd_points_non_negative', type_='check')
        batch.drop_column('cpd_points')
        batch.create_check_constraint(
            'ck_courses_cpd_points_online_non_negative',
            'cpd_points_online >= 0 OR cpd_points_online IS NULL',
        )
        batch.create_check_constraint(
            'ck_courses_cpd_points_offline_non_negative',
            'cpd_points_offline >= 0 OR cpd_points_offline IS NULL',
        )

    with op.batch_alter_table('course_instances') as batch:
        batch.drop_constraint(
            'ck_course_instances_cpd_points_non_negative', type_='check',
        )
        batch.drop_column('cpd_points')
        batch.create_check_constraint(
            'ck_course_instances_cpd_points_online_non_negative',
            'cpd_points_online >= 0 OR cpd_points_online IS NULL',
        )
        batch.create_check_constraint(
            'ck_course_instances_cpd_points_offline_non_negative',
            'cpd_points_offline >= 0 OR cpd_points_offline IS NULL',
        )

    with op.batch_alter_table('event_registrations') as batch:
        batch.alter_column('cpd_points_awarded', type_=sa.Numeric(5, 2))
        batch.add_column(sa.Column('participation_format', sa.String(20)))
        batch.create_check_constraint(
            'ck_event_registrations_participation_format',
            "participation_format IN ('online', 'offline') "
            "OR participation_format IS NULL",
        )
    op.execute(participation_format_backfill_sql())

    for table in ('certificates', 'lecturer_certificates', 'online_courses'):
        with op.batch_alter_table(table) as batch:
            batch.alter_column('cpd_points', type_=sa.Numeric(5, 2))


def downgrade():
    for table in ('certificates', 'lecturer_certificates', 'online_courses'):
        with op.batch_alter_table(table) as batch:
            batch.alter_column('cpd_points', type_=sa.Integer())

    with op.batch_alter_table('event_registrations') as batch:
        batch.drop_constraint(
            'ck_event_registrations_participation_format', type_='check',
        )
        batch.drop_column('participation_format')
        batch.alter_column('cpd_points_awarded', type_=sa.Integer())

    for table in POINTS_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('cpd_points', sa.Integer()))
        op.execute(collapse_points_sql(table))
        with op.batch_alter_table(table) as batch:
            batch.drop_column('cpd_points_online')
            batch.drop_column('cpd_points_offline')

    with op.batch_alter_table('courses') as batch:
        batch.alter_column('bpr_lecturer_points', type_=sa.Integer())
```

Підставити реальну голову з Кроку 1 у `down_revision` і в docstring.

- [ ] **Step 5: Прогнати тест міграції**

Run: `python -m pytest tests/test_db/test_migration_bpr_points_split.py -v`
Expected: PASS

- [ ] **Step 6: Застосувати міграцію на dev-БД і перевірити оборотність**

Run: `flask db upgrade && flask db downgrade -1 && flask db upgrade`
Expected: усі три кроки без помилок; після останнього `flask db heads` показує `bpr_points_split_20260909`

- [ ] **Step 7: Прогнати весь набір**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 8: Коміт**

```bash
git add migrations/versions/bpr_points_split_20260909_add_format_columns.py tests/test_db/test_migration_bpr_points_split.py
git commit -m "feat(db): міграція балів БПР на Numeric і розподіл за форматом

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Порядок деплою

1. Викотити зустрічну правку в `D:\site-mm-medic` (дві колонки, `Numeric`, читання нових ключів) -- **раніше** за цю задачу. Поки її немає, партнерські картки заходів показуватимуть бали порожніми.
2. `flask db upgrade` на проді.
3. Пройтись гібридними заходами в адмінці: після міграції в них обидва поля містять однакове старе значення, онлайнове треба проставити свідомо.
4. Звірити, що дзеркало mm-medic підхопило `cpd_points_online` / `cpd_points_offline`.
5. Перевірити розетки балів: у `app/static/images/certificates/` лежить лише `10-points-BPR.webp`, тож для інших номіналів фолбек лишається -- за потреби додати файли.
