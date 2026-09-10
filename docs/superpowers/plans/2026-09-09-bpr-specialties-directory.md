# Довідник спеціальностей для сертифіката -- план реалізації

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Замінити вільний текст «Спеціальності (для сертифіката)» вибором із довідника офіційної номенклатури -- з пошуком, кількома значеннями і можливістю зняти помилковий вибір.

**Architecture:** Номенклатура (розділи I-IV Додатка 1) розбирається з PDF одноразовим інструментом у `app/data/specialties.py`, звідки міграція сіє таблицю `specialties`. Курс і проведення посилаються на рядки довідника списком кодів (JSON), сертифікат друкує назви через кому. Вибір -- серверний `<select multiple>`, поверх якого JS малює чіпи й пошук; без JS лишається нативний мультиселект.

**Tech Stack:** Flask, SQLAlchemy, Alembic (batch_alter_table), WTForms 3.2, Jinja2, ванільний JS, CSS дизайн-системи (`admin.css`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-bpr-specialties-directory-design.md`

## Global Constraints

- Мова коментарів і рядків UI -- українська; тире в коментарях -- `--`, не «—».
- Емодзі в коді заборонені (CLAUDE.md). Інлайн-CSS і інлайн-JS заборонені: стилі -- у CSS-файлах, поведінка -- у `app/static/js/*.js`. Виняток -- шаблони сертифікатів (`app/templates/certificates/*.html`), які WeasyPrint рендерить окремо і які вже несуть власний `<style>`.
- Компонентні класи оголошуються ОДИН раз, у `admin.css`; `page-*.css` -- лише layout. Кожен новий компонентний клас мусить бути показаний у вітрині `app/templates/design_system/_tab_*.html`, інакше `tests/test_design_system/test_catalog_coverage.py` червоніє.
- Комітити напряму в `main`, без фіча-гілок. Коміт -- лише коли тести відповідної задачі зелені.
- Alembic-голова на момент планування -- `transfer_after_days_20260908`. Перед створенням ревізії звірити: `python -m flask db heads` (regex по файлах не бачить кортежних merge-ревізій).
- Тести піднімають схему через `db.create_all()`, а не через міграції (`tests/conftest.py:44`), тож нова колонка працює в тестах одразу після правки моделі.
- Тести, що створюють користувачів, мусять прибирати за собою: інакше валиться `test_api_v1_clients`.
- `pytest` запускати як `python -m pytest` з `venv`: `./venv/Scripts/python.exe -m pytest ...`.

---

### Task 1: Код рядка довідника і розбір номенклатури

**Files:**
- Create: `app/services/specialties.py`
- Create: `app/data/__init__.py`
- Create: `app/data/specialties.py` (генерується інструментом)
- Create: `tools/parse_specialties.py`
- Test: `tests/test_services/test_specialties_code.py`
- Test: `tests/test_services/test_specialties_data.py`

**Interfaces:**
- Consumes: `app.services.blog_service.slugify(text)` -- українська назва -> латинський slug у нижньому регістрі з дефісами.
- Produces:
  - `app.services.specialties.CODE_MAX_LENGTH = 60`
  - `app.services.specialties.specialty_code(name, taken=()) -> str`
  - `app.services.specialties.normalize_name(text) -> str`
  - `app.data.specialties.SPECIALTIES: list[tuple[str, str, str, int]]` -- `(code, name, section, sort_order)`, `section` -- один із `medical` / `pharmacy` / `professionals` / `specialists`.

- [ ] **Step 1: Написати тести на код рядка довідника**

Створити `tests/test_services/test_specialties_code.py`:

```python
"""Код рядка довідника спеціальностей: транслітерація, унікальність, довжина."""
from app.services.specialties import CODE_MAX_LENGTH, normalize_name, specialty_code


def test_code_is_latin_slug_of_ukrainian_name():
    assert specialty_code('Дитяча ендокринологія') == 'dytiacha-endokrynolohiia'


def test_code_collapses_separators():
    assert specialty_code('Загальна практика - сімейна медицина') == \
        'zahalna-praktyka-simeina-medytsyna'


def test_code_gets_suffix_when_taken():
    # "Бактеріологія" є і серед лікарських, і серед професіоналів.
    taken = {'bakteriolohiia'}
    assert specialty_code('Бактеріологія', taken=taken) == 'bakteriolohiia-2'


def test_code_suffix_repeats_until_free():
    taken = {'bakteriolohiia', 'bakteriolohiia-2'}
    assert specialty_code('Бактеріологія', taken=taken) == 'bakteriolohiia-3'


def test_code_fits_column():
    long_name = 'Лабораторні дослідження факторів навколишнього середовища людини'
    code = specialty_code(long_name)
    assert len(code) <= CODE_MAX_LENGTH
    assert not code.endswith('-')


def test_normalize_name_ignores_case_and_spacing():
    assert normalize_name('  Усі   Лікарські  Спеціальності ') == 'усі лікарські спеціальності'
```

- [ ] **Step 2: Запустити тести й переконатись, що падають**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_specialties_code.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'app.services.specialties'`

- [ ] **Step 3: Написати модуль служби (поки лише код і нормалізація)**

Створити `app/services/specialties.py`:

```python
"""Довідник спеціальностей для рядка «Спеціальності:» на сертифікаті.

Номенклатура (Додаток 1 до Порядку проведення атестації працівників сфери
охорони здоров'я) живе таблицею specialties: вона змінюється наказами МОЗ,
тож актуалізація -- робота адміністратора на /admin/specialties, а не
деплой.

Курс і проведення посилаються на рядки довідника КОДАМИ, а не FK на id:
код стабільний, читається в логах і переживає перезаливку довідника.
"""
from app.services.blog_service import slugify

# Ширина колонки specialties.code.
CODE_MAX_LENGTH = 60


def normalize_name(text):
    """Форма для звірки: без крайніх пробілів, стиснуті внутрішні, нижній
    регістр. Такою звіряється старий вільний текст курсу з назвами
    довідника."""
    return ' '.join((text or '').split()).lower()


def specialty_code(name, taken=()):
    """Код рядка довідника з української назви -- латинський slug.

    taken -- уже зайняті коди; при збігу додається -2, -3 ... Збіги реальні:
    "Бактеріологія" стоїть і серед лікарських спеціальностей, і серед
    спеціальностей професіоналів.

    Потрібно і парсеру номенклатури, і бекфілу міграції, тому живе тут, а не
    всередині інструмента.
    """
    base = slugify(name)[:CODE_MAX_LENGTH].strip('-') or 'specialty'
    code, n = base, 2
    while code in taken:
        suffix = f'-{n}'
        code = base[:CODE_MAX_LENGTH - len(suffix)].strip('-') + suffix
        n += 1
    return code
```

- [ ] **Step 4: Запустити тести й переконатись, що проходять**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_specialties_code.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Написати інструмент розбору PDF**

Створити `tools/parse_specialties.py`:

```python
"""Розбір Додатка 1 (номенклатура спеціальностей) у app/data/specialties.py.

Запускається РУКАМИ і одноразово:

    ./venv/Scripts/pip.exe install pypdf
    ./venv/Scripts/python.exe tools/parse_specialties.py dn_650_16042025_dod_3.pdf

pypdf у requirements НЕ додається: у рантаймі PDF не читається, довідник
живе в БД.

Парситься лише частина 1 Додатка ("Спеціальності та професійні
кваліфікації"), розділи I-IV. Частина 2 ("Профілі роботи за
спеціальностями") -- не спеціальності, і у виборі для сертифіката вона б
плутала.

Розбирається КОЛОНКА 2 таблиці (назва спеціальності). Колонка 3 -- позначка
"+" або порожньо, колонка 4 -- професійна кваліфікація; обидві відрізаються.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.specialties import specialty_code  # noqa: E402

# Ключ -- кирилична нумерація розділу з документа.
SECTIONS = {
    'І': 'medical',
    'ІІ': 'pharmacy',
    'ІІІ': 'professionals',
    'ІV': 'specialists',
}

# "ІІІ. СПЕЦІАЛЬНОСТІ ПРОФЕСІОНАЛІВ ..." -- заголовок розділу.
_SECTION_RE = re.compile(r'^(І|ІІ|ІІІ|ІV)\.\s+[А-ЯІЇЄҐ]')
# "2. Лікарські спеціальності ..." або "1) Лікарські спеціальності ..."
_SUBSECTION_RE = re.compile(r'^\d+[.)]\s')
# "12 Дитяча ендокринологія + Лікар-ендокринолог дитячий" або просто "3"
# (у широких рядках номер лишається сам на рядку).
_ENTRY_RE = re.compile(r'^(\d+)(?:\s+(.*))?$')
# Колонтитул сторінки і шапка колонок.
_NOISE_RE = re.compile(r'^(\d+\s+Продовження додатка|1 2 3 4$)')
# Межа між колонкою 2 і рештою рядка: " + " або два-плюс пробіли (порожня
# третя колонка дає саме їх).
_COLUMN_BREAK_RE = re.compile(r'\s\+\s|\s{2,}')
# Кваліфікації з колонки 4 -- якщо таке слово опинилось у назві, розбір з'їхав.
_QUALIFICATION_WORDS = ('Лікар', 'Фармацевт', 'Професіонал', 'Сестра',
                        'Експерт', 'Фельдшер', 'Акушерка')


def extract_lines(pdf_path):
    from pypdf import PdfReader

    lines = []
    for page in PdfReader(str(pdf_path)).pages:
        lines.extend((page.extract_text() or '').split('\n'))
    return lines


def parse(lines):
    """[(section, number, name)] у порядку появи в документі."""
    entries = []
    section = None
    current = None
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            if current is not None:
                # Порожній рядок усередині запису -- це межа колонок:
                # зберігаємо його як порожній шматок, щоб склейка дала
                # два пробіли й розрив спрацював.
                current[2].append('')
            continue
        if _NOISE_RE.match(stripped):
            continue
        head = _SECTION_RE.match(stripped)
        if head:
            if 'ПРОФІЛІ РОБОТИ' in stripped:
                break  # почалась частина 2 -- далі не наша справа
            section = SECTIONS[head.group(1)]
            current = None
            continue
        if _SUBSECTION_RE.match(stripped):
            current = None
            continue
        entry = _ENTRY_RE.match(stripped)
        if entry and section:
            current = [section, int(entry.group(1)), [entry.group(2) or '']]
            entries.append(current)
            continue
        if current is not None:
            current[2].append(stripped)
    return [(section, number, _name_from(chunks)) for section, number, chunks in entries]


def _name_from(chunks):
    """Назва спеціальності зі шматків рядка таблиці."""
    text = ''
    for chunk in chunks:
        if not text:
            text = chunk
        elif text.endswith('-'):
            # Перенесене слово: "Протезування-" + "ортезування".
            text += chunk
        else:
            text += ' ' + chunk
    name = _COLUMN_BREAK_RE.split(text.strip(), 1)[0]
    return ' '.join(name.split())


def problems(entries):
    """Чому розбору можна не вірити. Порожній список -- можна."""
    found = []
    expected, prev_section = 1, None
    for section, number, name in entries:
        if number == 1 or section != prev_section:
            expected = 1
        if number != expected:
            # У номенклатурі номери в підрозділі йдуть 1, 2, 3 ... без дірок.
            # Дірка або повтор означає, що рядок склеївся з сусіднім або
            # загубився.
            found.append(f'{section}: очікував номер {expected}, отримав {number} ({name!r})')
        expected = number + 1
        prev_section = section

        if not name:
            found.append(f'{section} #{number}: порожня назва')
        elif len(name) > 120:
            found.append(f'{section} #{number}: підозріло довга назва {name!r}')
        elif any(word in name for word in _QUALIFICATION_WORDS):
            found.append(f'{section} #{number}: у назву затекла кваліфікація {name!r}')
    return found


def to_rows(entries):
    """[(code, name, section, sort_order)] -- рівно те, що йде у файл даних."""
    rows, taken, order = [], set(), {}
    for section, _number, name in entries:
        code = specialty_code(name, taken=taken)
        taken.add(code)
        order[section] = order.get(section, 0) + 1
        rows.append((code, name, section, order[section]))
    return rows


def render_module(rows):
    body = '\n'.join(
        f'    ({code!r}, {name!r}, {section!r}, {sort_order}),'
        for code, name, section, sort_order in rows
    )
    return (
        '"""Номенклатура спеціальностей (Додаток 1, розділи I-IV).\n\n'
        'ЗГЕНЕРОВАНО tools/parse_specialties.py з dn_650_16042025_dod_3.pdf.\n'
        'Руками не правити: файл читає лише міграція specialties_20260909,\n'
        'а після неї довідник живе в БД і правиться в /admin/specialties.\n\n'
        'Рядок: (code, назва, розділ, порядок у розділі).\n'
        '"""\n'
        'SPECIALTIES = [\n'
        f'{body}\n'
        ']\n'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--out', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'app' / 'data' / 'specialties.py')
    args = parser.parse_args()

    entries = parse(extract_lines(args.pdf))
    found = problems(entries)
    counts = {}
    for section, _number, _name in entries:
        counts[section] = counts.get(section, 0) + 1
    print('Розібрано:', ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    for line in found:
        print('УВАГА:', line)
    if found:
        print(f'Проблем: {len(found)}. Файл НЕ записано.')
        return 1

    args.out.write_text(render_module(to_rows(entries)), encoding='utf-8')
    print(f'Записано {len(entries)} позицій у {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 6: Створити пакет даних**

Створити `app/data/__init__.py`:

```python
"""Статичні дані, згенеровані інструментами з tools/ і закомічені в репо."""
```

- [ ] **Step 7: Прогнати інструмент і довести розбір до нуля зауважень**

```bash
./venv/Scripts/pip.exe install pypdf
./venv/Scripts/python.exe tools/parse_specialties.py dn_650_16042025_dod_3.pdf
```

Очікується рядок `Розібрано: medical=~136, pharmacy=9, professionals=~29, specialists=~33` і `Записано ... позицій`.

Якщо друкуються рядки `УВАГА:` -- файл не записано, і це нормальний хід роботи: правити правила розбору в `parse`/`_name_from` (найімовірніші місця -- перенос слова через дефіс і рядки, де номер стоїть окремо), доки зауважень не лишиться. Не глушити перевірку: вона єдина стоїть між помилкою розбору і назвами в офіційному документі.

- [ ] **Step 8: Звірити вихід очима з PDF**

Відкрити `app/data/specialties.py` і звірити з `dn_650_16042025_dod_3.pdf` щонайменше:
- першу позицію розділу I -- `Загальна практика - сімейна медицина`;
- позицію з переносом слова -- `Протезування-ортезування` (розділ III);
- позицію з довгою назвою -- `Хірургія серця та магістральних судин` (розділ I);
- останню позицію розділу IV.

Помилку тут не спіймає жоден тест: у сертифікат іде рівно цей текст.

- [ ] **Step 9: Написати тест-сторож на файл даних**

Створити `tests/test_services/test_specialties_data.py`:

```python
"""Сторож згенерованого файлу номенклатури.

Тест не перевіряє кожну назву -- це робота очей при генерації. Він ловить
те, що ламає довідник мовчки: дублікат коду, чужий розділ, порожню назву,
затеклу в назву кваліфікацію і різке схуднення файлу після перегенерації.
"""
from app.data.specialties import SPECIALTIES

SECTIONS = {'medical', 'pharmacy', 'professionals', 'specialists'}
MIN_COUNT = {'medical': 100, 'pharmacy': 8, 'professionals': 25, 'specialists': 30}


def test_codes_are_unique():
    codes = [row[0] for row in SPECIALTIES]
    assert len(codes) == len(set(codes))


def test_codes_fit_column():
    assert all(0 < len(row[0]) <= 60 for row in SPECIALTIES)


def test_sections_are_known():
    assert {row[2] for row in SPECIALTIES} == SECTIONS


def test_names_are_not_empty_and_not_qualifications():
    for code, name, _section, _order in SPECIALTIES:
        assert name.strip(), code
        assert not name.startswith('Лікар'), code
        assert not name.startswith('Фармацевт'), code


def test_each_section_has_expected_volume():
    counts = {}
    for _code, _name, section, _order in SPECIALTIES:
        counts[section] = counts.get(section, 0) + 1
    for section, minimum in MIN_COUNT.items():
        assert counts.get(section, 0) >= minimum, (section, counts.get(section))


def test_sort_order_is_sequential_within_section():
    seen = {}
    for _code, _name, section, order in SPECIALTIES:
        seen.setdefault(section, []).append(order)
    for section, orders in seen.items():
        assert orders == list(range(1, len(orders) + 1)), section
```

- [ ] **Step 10: Запустити тести**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_specialties_code.py tests/test_services/test_specialties_data.py -v`
Expected: PASS

- [ ] **Step 11: Коміт**

```bash
git add app/services/specialties.py app/data/ tools/parse_specialties.py tests/test_services/test_specialties_code.py tests/test_services/test_specialties_data.py
git commit -m "feat(specialties): розбір номенклатури МОЗ у довідник-джерело

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Модель довідника і читальна частина служби

**Files:**
- Create: `app/models/specialty.py`
- Modify: `app/models/__init__.py` (додати імпорт поруч із `City`, рядок 41)
- Modify: `app/services/specialties.py` (дописати каталог)
- Test: `tests/test_services/test_specialties_catalog.py`

**Interfaces:**
- Consumes: `app.models.mixins.BigIntPK`, `TimestampMixin`, `TranslatableMixin`; `app.services.specialties.normalize_name`.
- Produces:
  - `app.models.specialty.Specialty` -- поля `code`, `name`, `section`, `is_group`, `sort_order`, `is_active`, `translations`; властивість `section_label`.
  - `app.models.specialty.SECTIONS` -- `(('medical', 'Лікарські'), ('pharmacy', 'Фармацевтичні'), ('professionals', 'Професіоналів'), ('specialists', 'Фахівців'))`, `SECTION_LABELS` -- той самий словником.
  - `app.services.specialties.catalog() -> dict[str, Specialty]`
  - `app.services.specialties.names(codes) -> list[str]`
  - `app.services.specialties.line(codes) -> str | None`
  - `app.services.specialties.choices(current=None) -> list[tuple[str, list[tuple[str, str]]]]`
  - `app.services.specialties.valid_codes() -> set[str]`

- [ ] **Step 1: Написати тести каталогу**

Створити `tests/test_services/test_specialties_catalog.py`:

```python
"""Читальна частина довідника: порядок, локалізація, вибір для форми."""
import pytest

from app.extensions import db
from app.models.specialty import Specialty
from app.services import specialties


@pytest.fixture
def catalog_rows():
    rows = [
        Specialty(code='all-medical', name='усі лікарські спеціальності',
                  section='medical', is_group=True, sort_order=0),
        Specialty(code='dermatovenerolohiia', name='Дерматовенерологія',
                  section='medical', sort_order=6),
        Specialty(code='alerholohiia', name='Алергологія',
                  section='medical', sort_order=2),
        Specialty(code='farmatsiia', name='Фармація',
                  section='pharmacy', sort_order=5),
        Specialty(code='stara-nazva', name='Стара назва',
                  section='medical', sort_order=99, is_active=False),
    ]
    db.session.add_all(rows)
    db.session.commit()
    return rows


def test_names_follow_nomenclature_order(app, catalog_rows):
    with app.test_request_context('/'):
        assert specialties.names(['dermatovenerolohiia', 'alerholohiia']) == \
            ['Алергологія', 'Дерматовенерологія']


def test_names_ignore_unknown_codes(app, catalog_rows):
    with app.test_request_context('/'):
        assert specialties.names(['alerholohiia', 'no-such-code']) == ['Алергологія']


def test_line_joins_with_comma(app, catalog_rows):
    with app.test_request_context('/'):
        assert specialties.line(['alerholohiia', 'dermatovenerolohiia']) == \
            'Алергологія, Дерматовенерологія'


def test_line_is_none_when_empty(app, catalog_rows):
    with app.test_request_context('/'):
        assert specialties.line([]) is None


def test_names_use_translation(app, catalog_rows):
    row = Specialty.query.filter_by(code='alerholohiia').one()
    row.set_translation('ru', 'name', 'Аллергология')
    db.session.commit()
    with app.test_request_context('/ru/'):
        assert specialties.names(['alerholohiia']) == ['Аллергология']


def test_choices_group_by_section_and_skip_inactive(app, catalog_rows):
    with app.test_request_context('/'):
        groups = dict(specialties.choices())
    assert [code for code, _label in groups['Лікарські']] == \
        ['all-medical', 'alerholohiia', 'dermatovenerolohiia']
    assert 'stara-nazva' not in [code for code, _ in groups['Лікарські']]


def test_choices_keep_current_even_if_deactivated(app, catalog_rows):
    with app.test_request_context('/'):
        groups = dict(specialties.choices(current=['stara-nazva']))
    assert 'stara-nazva' in [code for code, _label in groups['Лікарські']]


def test_valid_codes_contains_inactive_rows(app, catalog_rows):
    with app.test_request_context('/'):
        assert 'stara-nazva' in specialties.valid_codes()
```

- [ ] **Step 2: Запустити тести й переконатись, що падають**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_specialties_catalog.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'app.models.specialty'`

- [ ] **Step 3: Написати модель**

Створити `app/models/specialty.py`:

```python
"""Довідник спеціальностей для рядка «Спеціальності:» на сертифікаті.

Курс і проведення посилаються сюди списком КОДІВ (bpr_specialty_codes), а не
FK: код стабільний, читається в дампі й переживає перезаливку довідника.

Рядок, який десь уже вжито, не видаляють, а деактивують (is_active=False):
у виборі він зникає, а там, де вже проставлений, рендериться далі. Так
актуалізація номенклатури не лишає курси з осиротілим кодом.
"""
from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin, TranslatableMixin

# Розділи I-IV Додатка 1. Підпис -- шапка групи у виборі спеціальностей.
SECTIONS = (
    ('medical', 'Лікарські'),
    ('pharmacy', 'Фармацевтичні'),
    ('professionals', 'Професіоналів'),
    ('specialists', 'Фахівців'),
)
SECTION_LABELS = dict(SECTIONS)


class Specialty(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'specialties'
    __translatable__ = ('name',)

    id = db.Column(BigIntPK, primary_key=True)

    # Латинський slug української назви, згенерований один раз і заморожений.
    code = db.Column(db.String(60), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    section = db.Column(db.String(20), nullable=False, index=True)

    # Службове узагальнення ("усі лікарські спеціальності") -- рядок довідника,
    # а не окремий стан поля: обирається й друкується як будь-який інший.
    is_group = db.Column(db.Boolean, nullable=False, default=False)

    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    @property
    def section_label(self):
        return SECTION_LABELS.get(self.section, self.section)

    def __repr__(self):
        return f'<Specialty {self.code}>'
```

- [ ] **Step 4: Зареєструвати модель**

У `app/models/__init__.py` поруч із рядком 41 (`from app.models.city import City`) додати:

```python
from app.models.specialty import Specialty
```

Порядок рядків -- за абеткою модуля, як у решті файлу; звірити, чи модель треба додати ще й у `__all__` (якщо такий список у файлі є).

- [ ] **Step 5: Дописати каталог у службу**

У кінець `app/services/specialties.py` додати:

```python
import logging

from flask import g, has_app_context

logger = logging.getLogger(__name__)

_CACHE_ATTR = '_specialties_catalog'


def catalog():
    """{code: Specialty} -- один запит на HTTP-запит.

    Довідник читається цілком: він на дві сотні коротких рядків, а сторінка
    зі списком проведень інакше дала б запит на кожне проведення.
    """
    if has_app_context() and _CACHE_ATTR in g:
        return g.get(_CACHE_ATTR)

    from app.models.specialty import Specialty
    try:
        rows = Specialty.query.all()
        mapping = {row.code: row for row in rows}
    except Exception:
        # Довідник -- шар над збереженими кодами. Якщо таблиці ще немає (код
        # піднявся до міграції) або БД моргнула, сертифікат друкується без
        # рядка спеціальностей, але сторінка не падає.
        logger.exception('Specialties catalog unavailable')
        mapping = {}

    if has_app_context():
        setattr(g, _CACHE_ATTR, mapping)
    return mapping


def _order_key(row):
    from app.models.specialty import SECTIONS
    sections = [code for code, _label in SECTIONS]
    position = sections.index(row.section) if row.section in sections else len(sections)
    return (position, row.sort_order, row.name)


def names(codes):
    """Назви активною мовою в порядку номенклатури. Невідомий код -- пропуск."""
    known = catalog()
    rows = [known[code] for code in (codes or []) if code in known]
    return [row.t('name') for row in sorted(rows, key=_order_key)]


def line(codes):
    """Рядок для сертифіката: назви через кому. Порожньо -- None."""
    return ', '.join(names(codes)) or None


def choices(current=None):
    """[(підпис розділу, [(code, назва), ...])] для SelectMultipleField.

    Активні рядки ПЛЮС ті коди, що вже збережені (current), навіть якщо рядок
    деактивований. Інакше WTForms відхилить сабміт із "Not a valid choice", і
    адміністратор не збереже жодної правки старого курсу -- навіть правки
    заголовка, що спеціальностей не стосується.
    """
    from app.models.specialty import SECTIONS
    keep = set(current or ())
    groups = []
    for section, label in SECTIONS:
        rows = sorted(
            (row for row in catalog().values()
             if row.section == section and (row.is_active or row.code in keep)),
            key=_order_key,
        )
        if rows:
            groups.append((label, [(row.code, row.t('name')) for row in rows]))
    return groups


def valid_codes():
    """Усі коди довідника, включно з деактивованими."""
    return set(catalog())
```

- [ ] **Step 6: Запустити тести**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_specialties_catalog.py -v`
Expected: PASS (8 passed)

- [ ] **Step 7: Прогнати сусідні тести моделей**

Run: `./venv/Scripts/python.exe -m pytest tests/test_models tests/test_services -q`
Expected: PASS (нова модель не має чіпати наявні)

- [ ] **Step 8: Коміт**

```bash
git add app/models/specialty.py app/models/__init__.py app/services/specialties.py tests/test_services/test_specialties_catalog.py
git commit -m "feat(specialties): модель довідника і читальна частина служби

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Перехід поля курсу й проведення на коди

Задача атомарна: міграція прибирає `courses.bpr_specialties`, тож усі, хто його читає й пише, переїжджають у цьому ж коміті.

**Files:**
- Create: `migrations/versions/specialties_20260909.py`
- Modify: `app/models/course.py:17` (`__translatable__`), `:60` (колонка)
- Modify: `app/models/course_instance.py` (колонка + `effective_specialty_codes` поруч із `effective_cpd_points`, рядок 204)
- Modify: `app/models/certificate.py:50` (тип колонки знімка) і той самий знімок у моделі лекторського сертифіката
- Modify: `app/services/specialties.py` (дописати `effective_codes`, `usage`, `legacy_code_for`)
- Modify: `app/admin/forms.py:563` (CourseForm), `:702+` (CourseInstanceForm)
- Modify: `app/admin/routes_courses.py:87,130` (choices), `app/admin/routes_instances.py:33` (`_populate_choices`)
- Modify: `app/services/course_service.py:379` і `:450` (populate)
- Modify: `app/services/certificate_service.py:196` і `:735`
- Modify: `app/services/translation_registry.py:28` (прибрати мітку)
- Modify: `app/templates/admin/course_edit.html:152-157`, `app/templates/admin/instance_edit.html` (біля `cpd_points`, рядок 127)
- Test: `tests/test_services/test_specialties_effective.py`
- Test: `tests/test_routes/test_admin_course_specialties.py`

**Interfaces:**
- Consumes: `specialties.catalog/names/line/valid_codes/specialty_code/normalize_name` (Задачі 1-2); `app.data.specialties.SPECIALTIES`.
- Produces:
  - `Course.bpr_specialty_codes: list[str]`, `CourseInstance.bpr_specialty_codes: list[str] | None`
  - `CourseInstance.effective_specialty_codes -> list[str]`
  - `app.services.specialties.effective_codes(instance) -> list[str]`
  - `app.services.specialties.usage() -> dict[str, int]`
  - `app.services.specialties.legacy_code_for(text, name_to_code) -> tuple[str, str | None]`
  - Ревізія `specialties_20260909` (down_revision `transfer_after_days_20260908`).

- [ ] **Step 1: Написати тести на ефективний список і бекфіл-звірку**

Створити `tests/test_services/test_specialties_effective.py`:

```python
"""Ефективний список спеціальностей проведення і звірка старого тексту."""
import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.specialty import Specialty
from app.services import specialties


@pytest.fixture
def course(app):
    row = Course(title='Курс плазмотерапії', slug='kurs-plazmoterapii',
                 bpr_specialty_codes=['alerholohiia'])
    db.session.add(row)
    db.session.commit()
    return row


def test_instance_inherits_course_codes(course):
    instance = CourseInstance(course_id=course.id)
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_specialty_codes == ['alerholohiia']


def test_instance_override_wins(course):
    instance = CourseInstance(course_id=course.id,
                              bpr_specialty_codes=['dermatovenerolohiia'])
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_specialty_codes == ['dermatovenerolohiia']


def test_empty_override_falls_back_to_course(course):
    instance = CourseInstance(course_id=course.id, bpr_specialty_codes=[])
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_specialty_codes == ['alerholohiia']


def test_legacy_text_matches_known_name():
    name_to_code = {'усі лікарські спеціальності': 'all-medical'}
    assert specialties.legacy_code_for('  Усі лікарські  спеціальності ',
                                       name_to_code) == ('all-medical', None)


def test_legacy_text_without_match_becomes_new_row():
    name_to_code = {'усі лікарські спеціальності': 'all-medical'}
    code, missing = specialties.legacy_code_for('Косметологія та дерматологія',
                                                name_to_code)
    assert missing == 'Косметологія та дерматологія'
    assert code and code not in name_to_code.values()


def test_usage_counts_courses_and_instances(app, course):
    db.session.add(CourseInstance(course_id=course.id,
                                  bpr_specialty_codes=['dermatovenerolohiia']))
    db.session.add(Specialty(code='alerholohiia', name='Алергологія',
                             section='medical', sort_order=2))
    db.session.commit()
    counts = specialties.usage()
    assert counts.get('alerholohiia') == 1
    assert counts.get('dermatovenerolohiia') == 1
```

- [ ] **Step 2: Запустити тести й переконатись, що падають**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_specialties_effective.py -v`
Expected: FAIL -- `TypeError: 'bpr_specialty_codes' is an invalid keyword argument for Course`

- [ ] **Step 3: Змінити моделі**

У `app/models/course.py`:

- у списку `__translatable__` (рядок 17) прибрати `'bpr_specialties'`;
- замінити рядки 59-60:

```python
    # Спеціальності заходу БПР для сертифіката -- коди рядків довідника
    # specialties. Порожній список = у сертифікаті рядка «Спеціальності:» не
    # буде. Назви перекладаються в довіднику, а не тут: одна "Дерматовенерологія"
    # на всі курси.
    bpr_specialty_codes = db.Column(db.JSON, default=list)
```

У `app/models/course_instance.py` додати колонку поруч з іншими перевизначеннями і властивість поруч із `effective_cpd_points` (рядок 204):

```python
    # Перевизначення спеціальностей проведення. NULL/порожньо -- беремо курс.
    bpr_specialty_codes = db.Column(db.JSON)

    @property
    def effective_specialty_codes(self):
        """Коди спеціальностей проведення або, якщо не задані, коди курсу."""
        if self.bpr_specialty_codes:
            return list(self.bpr_specialty_codes)
        course = self.course
        return list(course.bpr_specialty_codes or []) if course else []
```

У `app/models/certificate.py` (рядок 50) і в моделі лекторського сертифіката замінити тип знімка:

```python
    # Знімок спеціальностей заходу на момент видачі (назви через кому).
    # Text, а не String(500): ліміту на кількість обраних позицій немає.
    specialties = db.Column(db.Text)
```

- [ ] **Step 4: Дописати службу**

У `app/services/specialties.py` додати:

```python
def effective_codes(instance):
    """Коди проведення або, якщо не задані, коди його курсу."""
    if instance is None:
        return []
    return instance.effective_specialty_codes


def usage():
    """{code: скільки курсів і проведень його вживають}.

    Адмінці довідника треба вага рядка: позицію з нулем можна видаляти, зайняту
    -- лише деактивувати. JSON-колонку рахуємо в пам'яті: рядків у курсах і
    проведеннях сотні, а SQL-джерела для JSON-масиву в SQLite і Postgres різні.
    """
    from app.extensions import db
    from app.models.course import Course
    from app.models.course_instance import CourseInstance

    counts = {}
    for model in (Course, CourseInstance):
        for (codes,) in db.session.query(model.bpr_specialty_codes).all():
            for code in (codes or []):
                counts[code] = counts.get(code, 0) + 1
    return counts


def legacy_code_for(text, name_to_code):
    """Код довідника для старого вільного тексту курсу.

    Повертає (code, missing_name). missing_name не None, коли збігу немає:
    міграція заводить такий рядок деактивованим, щоб значення не загубилось і
    курс не лишився з осиротілим кодом.
    """
    name = ' '.join((text or '').split())
    code = name_to_code.get(normalize_name(name))
    if code:
        return code, None
    return specialty_code(name, taken=set(name_to_code.values())), name
```

- [ ] **Step 5: Запустити тести служби**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_specialties_effective.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Написати міграцію**

Спершу звірити голову: `./venv/Scripts/python.exe -m flask db heads` -> має бути `transfer_after_days_20260908`. Якщо інша -- підставити її в `down_revision`.

Створити `migrations/versions/specialties_20260909.py`:

```python
"""Довідник спеціальностей і перехід курсу/проведення на коди

Revision ID: specialties_20260909
Revises: transfer_after_days_20260908
Create Date: 2026-09-09 00:00:00.000000

Поле "Спеціальності (для сертифіката)" було вільним рядком
(courses.bpr_specialties): назви набирали руками, і в сертифікат ішло те, що
набрали. Тепер номенклатура (Додаток 1 до Порядку проведення атестації
працівників сфери охорони здоров'я) лежить таблицею specialties, а курс і
проведення посилаються на неї списком кодів.

Наявні значення не губляться: текст звіряється з назвами довідника за
нормалізованою формою, а те, чого в довіднику немає, заводиться в нього
деактивованим рядком.

Знімки сертифікатів (certificates.specialties, lecturer_certificates.specialties)
лишаються рядками -- виданий документ не залежить від довідника -- але
переїжджають зі String(500) у Text: ліміту на кількість обраних позицій немає.
"""
from alembic import op
import sqlalchemy as sa


revision = 'specialties_20260909'
down_revision = 'transfer_after_days_20260908'
branch_labels = None
depends_on = None


# Узагальнення: службові рядки, які обираються як звичайні позиції.
_GROUPS = (
    ('all-medical', 'усі лікарські спеціальності', 'medical'),
    ('all-pharmacy', 'усі фармацевтичні спеціальності', 'pharmacy'),
    ('all-professionals',
     'усі спеціальності професіоналів у сфері охорони здоров’я',
     'professionals'),
    ('all-specialists',
     'усі спеціальності фахівців у сфері охорони здоров’я',
     'specialists'),
)


def upgrade():
    op.create_table(
        'specialties',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('section', sa.String(length=20), nullable=False),
        sa.Column('is_group', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('translations', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index('ix_specialties_code', 'specialties', ['code'])
    op.create_index('ix_specialties_section', 'specialties', ['section'])

    bind = op.get_bind()
    _seed(bind)

    with op.batch_alter_table('courses') as batch:
        batch.add_column(sa.Column('bpr_specialty_codes', sa.JSON(), nullable=True))
    with op.batch_alter_table('course_instances') as batch:
        batch.add_column(sa.Column('bpr_specialty_codes', sa.JSON(), nullable=True))

    _backfill(bind)

    with op.batch_alter_table('courses') as batch:
        batch.drop_column('bpr_specialties')

    _drop_translation_key(bind)

    with op.batch_alter_table('certificates') as batch:
        batch.alter_column('specialties', existing_type=sa.String(length=500),
                           type_=sa.Text(), existing_nullable=True)
    with op.batch_alter_table('lecturer_certificates') as batch:
        batch.alter_column('specialties', existing_type=sa.String(length=500),
                           type_=sa.Text(), existing_nullable=True)


def _seed(bind):
    """Позиції номенклатури плюс чотири узагальнення."""
    from app.data.specialties import SPECIALTIES

    rows = [{'code': code, 'name': name, 'section': section,
             'is_group': False, 'sort_order': sort_order, 'is_active': True}
            for code, name, section, sort_order in SPECIALTIES]
    rows.extend({'code': code, 'name': name, 'section': section,
                 'is_group': True, 'sort_order': 0, 'is_active': True}
                for code, name, section in _GROUPS)
    bind.execute(
        sa.text('INSERT INTO specialties (code, name, section, is_group, '
                'sort_order, is_active) VALUES (:code, :name, :section, '
                ':is_group, :sort_order, :is_active)'),
        rows,
    )


def _backfill(bind):
    """Старий вільний текст курсу -> список кодів."""
    from app.services.specialties import legacy_code_for, normalize_name

    name_to_code = {
        normalize_name(name): code
        for code, name in bind.execute(sa.text('SELECT code, name FROM specialties'))
    }
    courses = bind.execute(sa.text(
        "SELECT id, bpr_specialties FROM courses "
        "WHERE bpr_specialties IS NOT NULL AND bpr_specialties <> ''"
    )).fetchall()

    for course_id, text in courses:
        code, missing = legacy_code_for(text, name_to_code)
        if missing:
            # Значення, якого немає в номенклатурі, лишається в довіднику
            # деактивованим: у виборі його не пропонують, у наявних курсах
            # воно рендериться далі.
            bind.execute(
                sa.text('INSERT INTO specialties (code, name, section, is_group, '
                        'sort_order, is_active) VALUES (:code, :name, :section, '
                        'false, 999, false)'),
                {'code': code, 'name': missing, 'section': 'medical'},
            )
            name_to_code[normalize_name(missing)] = code
        bind.execute(
            sa.text('UPDATE courses SET bpr_specialty_codes = :codes WHERE id = :id'),
            {'codes': f'["{code}"]', 'id': course_id},
        )


def _drop_translation_key(bind):
    """Прибрати переклади поля, якого більше немає.

    Інакше ключ 'bpr_specialties' лишався б у courses.translations і виринав
    би в /admin/translations як одиниця перекладу без поля.
    """
    import json

    rows = bind.execute(sa.text(
        'SELECT id, translations FROM courses WHERE translations IS NOT NULL'
    )).fetchall()
    for course_id, stored in rows:
        data = json.loads(stored) if isinstance(stored, str) else stored
        if not isinstance(data, dict):
            continue
        changed = False
        for lang, values in list(data.items()):
            if isinstance(values, dict) and 'bpr_specialties' in values:
                values.pop('bpr_specialties')
                changed = True
        if changed:
            bind.execute(
                sa.text('UPDATE courses SET translations = :value WHERE id = :id'),
                {'value': json.dumps(data, ensure_ascii=False), 'id': course_id},
            )


def downgrade():
    bind = op.get_bind()

    with op.batch_alter_table('certificates') as batch:
        batch.alter_column('specialties', existing_type=sa.Text(),
                           type_=sa.String(length=500), existing_nullable=True)
    with op.batch_alter_table('lecturer_certificates') as batch:
        batch.alter_column('specialties', existing_type=sa.Text(),
                           type_=sa.String(length=500), existing_nullable=True)

    with op.batch_alter_table('courses') as batch:
        batch.add_column(sa.Column('bpr_specialties', sa.String(length=500),
                                   nullable=True))

    # Односторонній крок: назви склеюємо через кому і обрізаємо до 500
    # символів. Курс, у якому обрано десяток спеціальностей, після відкату
    # матиме урізаний рядок -- відновити його можна тільки повторним
    # накатом ревізії.
    names = dict(bind.execute(sa.text('SELECT code, name FROM specialties')))
    import json
    rows = bind.execute(sa.text(
        'SELECT id, bpr_specialty_codes FROM courses '
        'WHERE bpr_specialty_codes IS NOT NULL'
    )).fetchall()
    for course_id, stored in rows:
        codes = json.loads(stored) if isinstance(stored, str) else stored
        text = ', '.join(names[c] for c in (codes or []) if c in names)[:500]
        bind.execute(
            sa.text('UPDATE courses SET bpr_specialties = :value WHERE id = :id'),
            {'value': text or None, 'id': course_id},
        )

    with op.batch_alter_table('course_instances') as batch:
        batch.drop_column('bpr_specialty_codes')
    with op.batch_alter_table('courses') as batch:
        batch.drop_column('bpr_specialty_codes')

    op.drop_index('ix_specialties_section', table_name='specialties')
    op.drop_index('ix_specialties_code', table_name='specialties')
    op.drop_table('specialties')
```

- [ ] **Step 7: Прогнати міграцію на dev-БД**

```bash
./venv/Scripts/python.exe -m flask db upgrade
./venv/Scripts/python.exe -m flask db downgrade
./venv/Scripts/python.exe -m flask db upgrade
```

Expected: усі три команди без помилок; після першої `SELECT count(*) FROM specialties` дає число з файлу даних плюс 4.

`DATABASE_URL` з командного рядка мовчки ігнорується -- dev-БД береться з `DATABASE_URL_DEV`. Переконатись, що жене саме dev.

- [ ] **Step 8: Перевести форми на мультиселект**

У `app/admin/forms.py` замінити поле `CourseForm.bpr_specialties` (рядок 563):

```python
    bpr_specialty_codes = SelectMultipleField(
        'Спеціальності (для сертифіката)',
        validators=[Optional()],
        description='Друкуються рядком «Спеціальності: …» на сертифікаті. '
                    'Список -- офіційна номенклатура; choices присвоюються в роуті.',
    )
```

У `CourseInstanceForm` (клас із рядка 702) поруч із `cpd_points` додати:

```python
    bpr_specialty_codes = SelectMultipleField(
        'Спеціальності (для сертифіката)',
        validators=[Optional()],
        description='Залиште порожнім щоб взяти з курсу',
    )
```

Додати `SelectMultipleField` до імпорту з `wtforms` угорі файлу, якщо його там ще немає.

- [ ] **Step 9: Присвоїти choices у роутах**

У `app/admin/routes_courses.py` після `populate_trainer_choices(form)` (рядки 88 і 131) додати:

```python
    form.bpr_specialty_codes.choices = specialties.choices(
        current=(course.bpr_specialty_codes if course else None),
    )
```

(у `course_create` -- `current=None`; імпорт `from app.services import specialties` угорі файлу.)

У `app/admin/routes_instances.py` у `_populate_choices` (рядок 33) додати:

```python
    from app.services import specialties
    instance_codes = form.bpr_specialty_codes.data or []
    form.bpr_specialty_codes.choices = specialties.choices(current=instance_codes)
```

**Пастка:** `current` мусить містити вже збережені коди, інакше WTForms відхилить сабміт курсу з деактивованою позицією і збереження впаде на «Not a valid choice».

- [ ] **Step 10: Перевести запис у сервісі**

У `app/services/course_service.py` замінити рядок 379:

```python
    course.bpr_specialty_codes = form.bpr_specialty_codes.data or []
```

і в `populate_instance_from_form` поруч із рядком 450:

```python
    # Порожній вибір -- це "як у курсу", тож у БД лягає NULL, а не [].
    instance.bpr_specialty_codes = form.bpr_specialty_codes.data or None
```

- [ ] **Step 11: Перевести шаблони адмінки**

У `app/templates/admin/course_edit.html` замінити блок рядків 152-157:

```html
        <div class="form-group admin-form__full">
          <label for="bpr_specialty_codes">Спеціальності (для сертифіката)</label>
          {{ form.bpr_specialty_codes(class="form-input", id="bpr_specialty_codes", size=8) }}
          <small class="form-hint">Друкуються рядком «Спеціальності: …» на сертифікаті. Перелік -- чинна номенклатура; правиться в довіднику спеціальностей.</small>
        </div>
```

Виклик `{{ i18n.panes(tr, 'bpr_specialties', obj=course) }}` прибрати: переклад назви живе в довіднику. Якщо після цього макрос `i18n` у файлі більше ніде не вживається -- прибрати і його імпорт.

У `app/templates/admin/instance_edit.html` після групи `cpd_points` (рядок 127-129) додати:

```html
        <div class="form-group admin-form__full">
          <label for="bpr_specialty_codes">Спеціальності (для сертифіката)</label>
          {{ form.bpr_specialty_codes(class="form-input", id="bpr_specialty_codes", size=8) }}
          <small class="form-hint">Порожньо -- беруться з курсу.</small>
        </div>
```

- [ ] **Step 12: Перевести сертифікати**

У `app/services/certificate_service.py` замінити рядок 196:

```python
    specialties_line = specialties_service.line(
        instance.effective_specialty_codes if instance else [],
    )
```

і повертати `specialties_line` замість `specialties` у кортежі `_event_snapshot` (перейменувати змінну всюди в межах функції, щоб не затінювати імпортований модуль).

Рядок 735 (лекторський сертифікат):

```python
        specialties=specialties_service.line(instance.effective_specialty_codes),
```

Імпорт угорі файлу: `from app.services import specialties as specialties_service`.

- [ ] **Step 13: Прибрати мітку поля з реєстру перекладів**

У `app/services/translation_registry.py:28` прибрати `'bpr_specialties': 'Спеціальності БПР',` зі словника `FIELD_LABELS`.

- [ ] **Step 14: Написати тест адмінської форми курсу**

Створити `tests/test_routes/test_admin_course_specialties.py`:

```python
"""Збереження спеціальностей курсу через адмінську форму."""
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.specialty import Specialty
from app.models.user import User


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'spec-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    # Прибираємо за собою: інакше валиться test_api_v1_clients.
    db.session.delete(user)
    db.session.commit()


@pytest.fixture
def rows():
    db.session.add_all([
        Specialty(code='alerholohiia', name='Алергологія', section='medical',
                  sort_order=2),
        Specialty(code='stara-nazva', name='Стара назва', section='medical',
                  sort_order=99, is_active=False),
    ])
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _course(**kwargs):
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=uuid4().hex[:8], **kwargs)
    db.session.add(course)
    db.session.commit()
    return course


def test_form_saves_selected_codes(client, admin, rows):
    _login(client, admin)
    course = _course()
    response = client.post(f'/admin/courses/{course.id}/edit', data={
        'title': course.title, 'slug': course.slug,
        'bpr_specialty_codes': ['alerholohiia'],
    }, follow_redirects=True)
    assert response.status_code == 200
    assert db.session.get(Course, course.id).bpr_specialty_codes == ['alerholohiia']


def test_form_rejects_unknown_code(client, admin, rows):
    _login(client, admin)
    course = _course()
    client.post(f'/admin/courses/{course.id}/edit', data={
        'title': course.title, 'slug': course.slug,
        'bpr_specialty_codes': ['no-such-code'],
    })
    assert db.session.get(Course, course.id).bpr_specialty_codes in (None, [])


def test_course_with_deactivated_code_still_saves(client, admin, rows):
    _login(client, admin)
    course = _course(bpr_specialty_codes=['stara-nazva'])
    response = client.post(f'/admin/courses/{course.id}/edit', data={
        'title': 'Нова назва курсу', 'slug': course.slug,
        'bpr_specialty_codes': ['stara-nazva'],
    }, follow_redirects=True)
    assert response.status_code == 200
    saved = db.session.get(Course, course.id)
    assert saved.title == 'Нова назва курсу'
    assert saved.bpr_specialty_codes == ['stara-nazva']
```

Поля форми курсу, обов'язкові для валідації, можуть відрізнятись від наведених `title`/`slug`: перед прогоном звірити `CourseForm` (`app/admin/forms.py:442`) і додати ті, що мають `DataRequired`.

- [ ] **Step 15: Запустити тести задачі**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_specialties_effective.py tests/test_routes/test_admin_course_specialties.py -v`
Expected: PASS

- [ ] **Step 16: Прогнати сертифікатні й курсові тести**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services tests/test_routes -q`
Expected: PASS. Тести, що ставили `bpr_specialties='усі лікарські спеціальності'`, треба перевести на `bpr_specialty_codes=['all-medical']` разом із рядком довідника у фікстурі.

- [ ] **Step 17: Коміт**

```bash
git add migrations/versions/specialties_20260909.py app/models app/services app/admin app/templates/admin tests
git commit -m "feat(specialties): курс і проведення обирають спеціальності з довідника

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Компонент мультиселекта

**Files:**
- Modify: `app/static/css/admin.css` (новий блок `.admin-multiselect`)
- Create: `app/static/js/admin-multiselect.js`
- Modify: `app/templates/design_system/_tab_admin.html` (картка компонента)
- Modify: `app/templates/admin/course_edit.html`, `app/templates/admin/instance_edit.html` (атрибут `data-multiselect` і підключення скрипта)

**Interfaces:**
- Consumes: `<select multiple data-multiselect>` з `<optgroup>`, відрендерений WTForms у Задачі 3.
- Produces: компонент не має JS-API; джерело правди -- сам `<select>`, тож сабміт лишається звичайним `getlist`.

- [ ] **Step 1: Додати стилі компонента в дизайн-систему**

У `app/static/css/admin.css` дописати блок (тільки токени, жодних сирих кольорів):

```css
/* ---- Мультиселект (чіпи + пошук над нативним <select multiple>) ---- */
.admin-multiselect { position: relative; display: block; }
.admin-multiselect__control {
  display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
  min-height: 42px; padding: 6px 8px;
  border: 1px solid var(--iprm-border); border-radius: var(--iprm-radius-md);
  background: var(--iprm-white);
}
.admin-multiselect__control:focus-within { border-color: var(--iprm-accent); }
.admin-multiselect__chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 999px;
  background: var(--iprm-surface-inset); color: var(--iprm-text);
  font-size: 13px;
}
.admin-multiselect__chip-remove {
  border: 0; background: none; cursor: pointer; padding: 0;
  color: var(--iprm-text-secondary); line-height: 1;
}
.admin-multiselect__search {
  flex: 1 1 120px; min-width: 120px; border: 0; outline: none;
  background: none; color: var(--iprm-text); font: inherit; padding: 4px;
}
.admin-multiselect__list {
  position: absolute; z-index: 20; left: 0; right: 0; top: calc(100% + 4px);
  max-height: 260px; overflow-y: auto; padding: 4px 0; margin: 0;
  list-style: none; background: var(--iprm-white);
  border: 1px solid var(--iprm-border); border-radius: var(--iprm-radius-md);
  box-shadow: var(--iprm-shadow-md);
}
.admin-multiselect__group {
  padding: 6px 12px; font-size: 12px; text-transform: uppercase;
  color: var(--iprm-text-secondary);
}
.admin-multiselect__option { padding: 6px 12px; cursor: pointer; }
.admin-multiselect__option:hover,
.admin-multiselect__option[aria-selected="true"] { background: var(--iprm-surface-inset); }
.admin-multiselect__empty { padding: 8px 12px; color: var(--iprm-text-secondary); }
```

Перед набором звірити наявні імена токенів у `admin.css` / `common.css` (`--iprm-border`, `--iprm-surface-inset`, `--iprm-radius-md`, `--iprm-shadow-md`) і замінити на ті, що справді оголошені: вигаданий токен мовчки дасть прозорий фон.

- [ ] **Step 2: Написати поведінку**

Створити `app/static/js/admin-multiselect.js`:

```javascript
/* Мультиселект: чіпи й пошук поверх нативного <select multiple>.
 *
 * Прогресивне покращення: без цього скрипта сторінка лишається робочою --
 * видно звичайний мультиселект, сабміт іде тим самим ім'ям поля.
 * Джерело правди -- сам <select>: компонент лише малює його стан.
 */
(function () {
  'use strict';

  function normalize(text) {
    return (text || '').toLowerCase().trim();
  }

  function build(select) {
    var wrap = document.createElement('div');
    wrap.className = 'admin-multiselect';
    var control = document.createElement('div');
    control.className = 'admin-multiselect__control';
    var search = document.createElement('input');
    search.type = 'text';
    search.className = 'admin-multiselect__search';
    search.setAttribute('role', 'combobox');
    search.setAttribute('aria-expanded', 'false');
    search.setAttribute('aria-autocomplete', 'list');
    search.placeholder = select.dataset.multiselectPlaceholder || 'Пошук…';
    var list = document.createElement('ul');
    list.className = 'admin-multiselect__list';
    list.hidden = true;
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-multiselectable', 'true');

    control.appendChild(search);
    wrap.appendChild(control);
    wrap.appendChild(list);
    select.parentNode.insertBefore(wrap, select);
    select.hidden = true;
    select.setAttribute('tabindex', '-1');

    var label = select.id && document.querySelector('label[for="' + select.id + '"]');
    if (label) { search.setAttribute('aria-label', label.textContent.trim()); }

    return { wrap: wrap, control: control, search: search, list: list };
  }

  function renderChips(select, ui) {
    Array.prototype.slice.call(
      ui.control.querySelectorAll('.admin-multiselect__chip')
    ).forEach(function (chip) { chip.remove(); });

    Array.prototype.filter.call(select.options, function (option) {
      return option.selected;
    }).forEach(function (option) {
      var chip = document.createElement('span');
      chip.className = 'admin-multiselect__chip';
      chip.textContent = option.textContent.trim();
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'admin-multiselect__chip-remove';
      remove.setAttribute('aria-label', 'Прибрати ' + option.textContent.trim());
      remove.textContent = '×';
      remove.addEventListener('click', function () {
        option.selected = false;
        renderChips(select, ui);
        renderList(select, ui);
      });
      chip.appendChild(remove);
      ui.control.insertBefore(chip, ui.search);
    });
  }

  function renderList(select, ui) {
    var needle = normalize(ui.search.value);
    ui.list.textContent = '';
    var shown = 0;

    Array.prototype.forEach.call(select.children, function (node) {
      var options = node.tagName === 'OPTGROUP'
        ? Array.prototype.slice.call(node.children)
        : [node];
      var matching = options.filter(function (option) {
        return !option.selected && normalize(option.textContent).indexOf(needle) !== -1;
      });
      if (!matching.length) { return; }
      if (node.tagName === 'OPTGROUP') {
        var head = document.createElement('li');
        head.className = 'admin-multiselect__group';
        head.textContent = node.label;
        head.setAttribute('role', 'presentation');
        ui.list.appendChild(head);
      }
      matching.forEach(function (option) {
        var item = document.createElement('li');
        item.className = 'admin-multiselect__option';
        item.textContent = option.textContent.trim();
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', 'false');
        item.addEventListener('mousedown', function (event) {
          event.preventDefault();
          option.selected = true;
          ui.search.value = '';
          renderChips(select, ui);
          renderList(select, ui);
        });
        ui.list.appendChild(item);
        shown += 1;
      });
    });

    if (!shown) {
      var empty = document.createElement('li');
      empty.className = 'admin-multiselect__empty';
      empty.textContent = 'Нічого не знайдено';
      ui.list.appendChild(empty);
    }
  }

  function open(ui, isOpen) {
    ui.list.hidden = !isOpen;
    ui.search.setAttribute('aria-expanded', String(isOpen));
  }

  function active(ui) {
    return ui.list.querySelector('.admin-multiselect__option[aria-selected="true"]');
  }

  function move(ui, delta) {
    var items = Array.prototype.slice.call(
      ui.list.querySelectorAll('.admin-multiselect__option')
    );
    if (!items.length) { return; }
    var current = items.indexOf(active(ui));
    items.forEach(function (item) { item.setAttribute('aria-selected', 'false'); });
    var next = items[Math.min(items.length - 1, Math.max(0, current + delta))]
      || items[0];
    next.setAttribute('aria-selected', 'true');
    next.scrollIntoView({ block: 'nearest' });
  }

  function enhance(select) {
    var ui = build(select);
    renderChips(select, ui);
    renderList(select, ui);

    ui.control.addEventListener('click', function () { ui.search.focus(); });
    ui.search.addEventListener('focus', function () {
      renderList(select, ui);
      open(ui, true);
    });
    ui.search.addEventListener('input', function () {
      renderList(select, ui);
      open(ui, true);
    });
    ui.search.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown') { event.preventDefault(); move(ui, 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); move(ui, -1); }
      else if (event.key === 'Enter') {
        var item = active(ui);
        if (item) {
          event.preventDefault();
          item.dispatchEvent(new MouseEvent('mousedown'));
        }
      } else if (event.key === 'Escape') { open(ui, false); }
      else if (event.key === 'Backspace' && !ui.search.value) {
        var selected = Array.prototype.filter.call(select.options, function (option) {
          return option.selected;
        });
        if (selected.length) {
          selected[selected.length - 1].selected = false;
          renderChips(select, ui);
          renderList(select, ui);
        }
      }
    });
    document.addEventListener('click', function (event) {
      if (!ui.wrap.contains(event.target)) { open(ui, false); }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    Array.prototype.forEach.call(
      document.querySelectorAll('select[multiple][data-multiselect]'),
      enhance
    );
  });
}());
```

- [ ] **Step 3: Увімкнути компонент у формах**

У `app/templates/admin/course_edit.html` і `app/templates/admin/instance_edit.html` додати атрибут у виклик поля:

```html
          {{ form.bpr_specialty_codes(class="form-input", id="bpr_specialty_codes", size=8, **{'data-multiselect': ''}) }}
```

і підключити скрипт у блоці `extra_js` цих сторінок поруч із наявними:

```html
<script src="{{ url_for('static', filename='js/admin-multiselect.js') }}?v={{ assets_version }}" defer></script>
```

Звірити ім'я блоку (`extra_js` / `scripts`) у `app/templates/admin/base_admin.html`.

- [ ] **Step 4: Показати компонент у вітрині**

У `app/templates/design_system/_tab_admin.html` додати картку (у тому ж форматі, що сусідні: `h3.ds-section-heading` + `div.ds-demo` + `p.ds-hint`):

```html
    <h3 class="ds-section-heading">Мультиселект</h3>
    <div class="ds-demo">
      <div class="admin-multiselect">
        <div class="admin-multiselect__control">
          <span class="admin-multiselect__chip">Алергологія
            <button type="button" class="admin-multiselect__chip-remove" aria-label="Прибрати Алергологія">&times;</button>
          </span>
          <span class="admin-multiselect__chip">Дерматовенерологія
            <button type="button" class="admin-multiselect__chip-remove" aria-label="Прибрати Дерматовенерологія">&times;</button>
          </span>
          <input type="text" class="admin-multiselect__search" placeholder="Пошук…" aria-label="Пошук спеціальності">
        </div>
        <ul class="admin-multiselect__list" role="listbox" aria-multiselectable="true">
          <li class="admin-multiselect__group" role="presentation">Лікарські</li>
          <li class="admin-multiselect__option" role="option" aria-selected="false">Ендокринологія</li>
          <li class="admin-multiselect__option" role="option" aria-selected="true">Кардіологія</li>
          <li class="admin-multiselect__empty">Нічого не знайдено</li>
        </ul>
      </div>
    </div>
    <p class="ds-hint">.admin-multiselect: чіпи й пошук поверх нативного &lt;select multiple data-multiselect&gt; (admin-multiselect.js). Джерело правди -- сам select, тож без JS форма лишається робочою, а сабміт іде звичайним getlist. Тут демо статичне: список показано розгорнутим навмисно.</p>
```

- [ ] **Step 5: Прогнати сторожів дизайн-системи**

Run: `./venv/Scripts/python.exe -m pytest tests/test_design_system -v`
Expected: PASS. Якщо `test_catalog_coverage` називає незгаданий клас -- дописати його в картку; якщо `test_component_ownership` свариться на дубль -- перевірити, що блок оголошений лише в `admin.css`.

- [ ] **Step 6: Перевірити числа дизайн-системи**

Run: `./venv/Scripts/python.exe tools/ds/ds_audit.py`
Expected: звіт без нових дублів класів.

- [ ] **Step 7: Перевірити сторінку очима**

Підняти застосунок і відкрити `/admin/courses/<id>/edit`: чіпи малюються, пошук фільтрує, хрестик знімає вибір, Backspace у порожньому пошуку знімає останній чіп. Потім вимкнути JS у devtools і перезавантажити: має лишитись нативний мультиселект, і збереження має працювати.

- [ ] **Step 8: Коміт**

```bash
git add app/static/css/admin.css app/static/js/admin-multiselect.js app/templates/design_system/_tab_admin.html app/templates/admin/course_edit.html app/templates/admin/instance_edit.html
git commit -m "feat(ds): мультиселект із пошуком і чіпами

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Сторінка довідника в адмінці

**Files:**
- Create: `app/admin/routes_specialties.py`
- Create: `app/templates/admin/specialties.html`
- Create: `app/static/css/page-admin-specialties.css`
- Modify: `app/admin/routes.py:7` (імпорт модуля роутів)
- Modify: `app/rbac/registry.py:72` (модуль прав)
- Modify: `app/templates/admin/partials/_sidebar.html:19,40` (пункт меню й перелік у `can_any`)
- Test: `tests/test_routes/test_admin_specialties.py`

**Interfaces:**
- Consumes: `specialties.usage()`, `specialties.catalog()`, `Specialty`, `SECTIONS`; `app.admin._listing`, `app.admin._helpers.try_commit`, `app.rbac.permission_required`.
- Produces: ендпойнти `admin.specialties_list`, `admin.specialties_save`, `admin.specialties_add`, `admin.specialties_delete`; права `specialties.view` / `.manage` / `.delete`.

- [ ] **Step 1: Написати тести сторінки**

Створити `tests/test_routes/test_admin_specialties.py`:

```python
"""Адмінка довідника спеціальностей: доступ, збереження, додавання, видалення."""
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.specialty import Specialty
from app.models.user import User


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'sp-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    db.session.delete(user)
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


@pytest.fixture
def row():
    specialty = Specialty(code=f'kod-{uuid4().hex[:6]}', name='Алергологія',
                          section='medical', sort_order=2)
    db.session.add(specialty)
    db.session.commit()
    return specialty


def test_requires_permission(client):
    assert client.get('/admin/specialties').status_code in (302, 401, 403)


def test_list_renders_rows(client, admin, row):
    _login(client, admin)
    response = client.get('/admin/specialties')
    assert response.status_code == 200
    assert 'Алергологія' in response.get_data(as_text=True)


def test_add_creates_row_with_generated_code(client, admin):
    _login(client, admin)
    client.post('/admin/specialties/add',
                data={'name': 'Дитяча ендокринологія', 'section': 'medical'})
    assert Specialty.query.filter_by(code='dytiacha-endokrynolohiia').count() == 1


def test_add_rejects_empty_name(client, admin):
    _login(client, admin)
    before = Specialty.query.count()
    client.post('/admin/specialties/add', data={'name': '  ', 'section': 'medical'})
    assert Specialty.query.count() == before


def test_save_writes_translation_and_flags(client, admin, row):
    _login(client, admin)
    response = client.post('/admin/specialties/save', data={
        f'tr__ru__{row.id}': 'Аллергология',
        f'order__{row.id}': '7',
    })
    assert response.status_code == 302
    saved = db.session.get(Specialty, row.id)
    assert saved.t('name', lang='ru') == 'Аллергология'
    assert saved.sort_order == 7
    # Галка не прийшла у формі -- рядок деактивовано.
    assert saved.is_active is False


def test_delete_refuses_used_row(client, admin, row):
    _login(client, admin)
    course = Course(title='Курс', slug=f'c-{uuid4().hex[:6]}',
                    bpr_specialty_codes=[row.code])
    db.session.add(course)
    db.session.commit()

    client.post(f'/admin/specialties/{row.id}/delete')
    assert db.session.get(Specialty, row.id) is not None


def test_delete_removes_unused_row(client, admin, row):
    _login(client, admin)
    client.post(f'/admin/specialties/{row.id}/delete')
    assert db.session.get(Specialty, row.id) is None
```

- [ ] **Step 2: Запустити тести й переконатись, що падають**

Run: `./venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_specialties.py -v`
Expected: FAIL -- 404 на `/admin/specialties`

- [ ] **Step 3: Написати роути**

Створити `app/admin/routes_specialties.py`:

```python
"""Адмінка довідника спеціальностей: назва, розділ, переклади, порядок,
активність -- одна таблиця, один сабміт.

Рядків тут дві сотні, тож над таблицею стоять пошук і фільтр за розділом.
Збереження читає ТІЛЬКИ ті ключі форми, що прийшли, тож збереження
відфільтрованої таблиці не чіпає решту довідника.
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.admin._helpers import try_commit
from app.extensions import db
from app.i18n import PREFIXED_LANGUAGES
from app.models.specialty import SECTIONS, SECTION_LABELS, Specialty
from app.rbac import permission_required
from app.services import specialties as specialties_service

audit_logger = logging.getLogger('audit')


@admin_bp.route('/specialties', methods=['GET'])
@permission_required('specialties.view')
def specialties_list():
    filters = {
        'q': _listing.text_arg('q'),
        'section': _listing.choice_arg('section', SECTION_LABELS),
    }
    query = Specialty.query
    if filters['section']:
        query = query.filter(Specialty.section == filters['section'])
    query = _listing.apply_search(query, filters['q'], [Specialty.name, Specialty.code])
    items = query.order_by(Specialty.section, Specialty.sort_order, Specialty.name).all()

    usage = specialties_service.usage()
    rows = []
    for specialty in items:
        stored = specialty.translations or {}
        # Ключ саме 'tr': row.values у Jinja дало б метод dict.values.
        translations = {lang: ((stored.get(lang) or {}).get('name') or '')
                        for lang in PREFIXED_LANGUAGES}
        rows.append({
            'specialty': specialty,
            'tr': translations,
            'uses': usage.get(specialty.code, 0),
        })

    return render_template(
        'admin/specialties.html',
        rows=rows,
        sections=SECTIONS,
        languages=PREFIXED_LANGUAGES,
        total=Specialty.query.count(),
        filters=filters,
        filter_args=_listing.filter_args(filters),
    )


@admin_bp.route('/specialties/save', methods=['POST'])
@permission_required('specialties.manage')
def specialties_save():
    """Зберегти показані рядки. Ключі, яких у формі немає, не чіпаються."""
    touched = 0
    for specialty in Specialty.query.all():
        marker = f'row__{specialty.id}'
        if marker not in request.form:
            continue
        touched += 1
        for lang in PREFIXED_LANGUAGES:
            value = (request.form.get(f'tr__{lang}__{specialty.id}') or '').strip()
            specialty.set_translation(lang, 'name', value or None)
        order = (request.form.get(f'order__{specialty.id}') or '').strip()
        if order.isdigit():
            specialty.sort_order = int(order)
        # Чекбокс приходить лише коли ввімкнений -- саме так знімають рядок.
        specialty.is_active = f'active__{specialty.id}' in request.form

    if try_commit(log_context='specialties_save'):
        audit_logger.info('Admin %s updated specialties (%s rows)',
                          current_user.email, touched)
        flash('Довідник збережено.', 'success')
    return redirect(url_for('admin.specialties_list'))


@admin_bp.route('/specialties/add', methods=['POST'])
@permission_required('specialties.manage')
def specialties_add():
    name = (request.form.get('name') or '').strip()
    section = request.form.get('section') or ''
    if not name or section not in SECTION_LABELS:
        flash('Вкажіть назву і розділ', 'error')
        return redirect(url_for('admin.specialties_list'))

    taken = {row.code for row in Specialty.query.all()}
    code = specialties_service.specialty_code(name, taken=taken)
    last = (Specialty.query.filter_by(section=section)
            .order_by(Specialty.sort_order.desc()).first())
    db.session.add(Specialty(
        code=code, name=name, section=section,
        sort_order=(last.sort_order + 1) if last else 1,
    ))
    if try_commit(log_context=f'specialties_add name={name!r}'):
        audit_logger.info('Admin %s added specialty %r (%s)',
                          current_user.email, name, code)
        flash(f'Додано "{name}". Впишіть переклади і збережіть.', 'success')
    return redirect(url_for('admin.specialties_list', **_listing.filter_args({})))


@admin_bp.route('/specialties/<int:specialty_id>/delete', methods=['POST'])
@permission_required('specialties.delete')
def specialties_delete(specialty_id):
    specialty = db.session.get(Specialty, specialty_id)
    if specialty is None:
        flash('Спеціальність не знайдено', 'error')
        return redirect(url_for('admin.specialties_list'))

    uses = specialties_service.usage().get(specialty.code, 0)
    if uses:
        # Видалити зайнятий рядок означало б лишити курси з осиротілим кодом.
        flash(f'"{specialty.name}" вживається у {uses} курсах/проведеннях. '
              f'Зніміть галку «Активна» замість видалення.', 'error')
        return redirect(url_for('admin.specialties_list'))

    name = specialty.name
    db.session.delete(specialty)
    if try_commit(log_context=f'specialties_delete id={specialty_id}'):
        audit_logger.info('Admin %s deleted specialty %r', current_user.email, name)
        flash(f'"{name}" видалено з довідника.', 'success')
    return redirect(url_for('admin.specialties_list'))
```

- [ ] **Step 4: Зареєструвати модуль роутів**

У `app/admin/routes.py` поруч із рядком 7 додати:

```python
from app.admin import routes_specialties  # noqa: F401
```

- [ ] **Step 5: Додати права і пункт сайдбару**

У `app/rbac/registry.py` після модуля `cities` (рядок 72-73):

```python
    Module('specialties', 'Довідник спеціальностей', 'content', _VMD,
           endpoint='admin.specialties_list'),
```

У `app/templates/admin/partials/_sidebar.html`: додати `'specialties.view'` у перелік `can_any(...)` (рядок 19) і після блоку локацій (рядки 40-45):

```html
      {% if can('specialties.view') %}
      <a href="{{ url_for('admin.specialties_list') }}" class="admin-sidebar__link admin-sidebar__link--sub{% if ep in ('admin.specialties_list', 'admin.specialties_save', 'admin.specialties_add', 'admin.specialties_delete') %} admin-sidebar__link--active{% endif %}">
        {{ icon('table_view') }}
        <span class="admin-sidebar__text">Довідник спеціальностей</span>
      </a>
      {% endif %}
```

- [ ] **Step 6: Написати шаблон сторінки**

Створити `app/templates/admin/specialties.html` за взірцем `app/templates/admin/cities.html`: `admin-hero` із заголовком «Довідник спеціальностей» і підзаголовком «Перелік із чинної номенклатури. Зайнятий рядок не видаляють, а деактивують»; `filter_bar` з пошуком (`q`) і селектом розділу (`section`); форма додавання (назва + розділ); таблиця `admin-table` з колонками: Назва (uk), Розділ, ru, en, Порядок, Активна, Використань, дія «Видалити».

Кожен рядок таблиці мусить нести прихований маркер, за яким `specialties_save` розуміє, що рядок був показаний:

```html
              <input type="hidden" name="row__{{ row.specialty.id }}" value="1">
```

Layout сторінки (ширини колонок, сітка панелей) -- у `app/static/css/page-admin-specialties.css`; декору (кольори, межі, тіні) там бути не повинно: усе це вже є в компонентних класах `admin.css`.

- [ ] **Step 7: Запустити тести сторінки**

Run: `./venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_specialties.py -v`
Expected: PASS (7 passed)

- [ ] **Step 8: Прогнати тести прав**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rbac -q`
Expected: PASS. Якщо тест матриці прав рахує модулі -- оновити очікуване число.

- [ ] **Step 9: Коміт**

```bash
git add app/admin/routes_specialties.py app/admin/routes.py app/rbac/registry.py app/templates/admin/specialties.html app/templates/admin/partials/_sidebar.html app/static/css/page-admin-specialties.css tests/test_routes/test_admin_specialties.py
git commit -m "feat(admin): сторінка довідника спеціальностей

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Рядок спеціальностей на сертифікаті

**Files:**
- Modify: `app/services/certificate_service.py` (поруч із `_event_size_class`, рядок 352, і контекст рендеру, рядок 454)
- Modify: `app/templates/certificates/certificate.html` (стилі біля рядка 108, метаблок -- рядок 197)
- Modify: `app/templates/certificates/certificate_compact.html` (стилі біля рядка 121, метаблок -- рядок 210)
- Modify: `app/admin/routes_tools.py:59,66` (демо-дані прев'ю)
- Test: `tests/test_services/test_certificate_specialties.py`

**Interfaces:**
- Consumes: `specialties.line(codes)`, `CourseInstance.effective_specialty_codes`.
- Produces: `certificate_service._specialties_size_class(text) -> str`; змінна шаблону `specialties_size_class`.

- [ ] **Step 1: Написати тести**

Створити `tests/test_services/test_certificate_specialties.py`:

```python
"""Рядок «Спеціальності:» у сертифікаті: джерело, порядок, розмір шрифту."""
from app.services.certificate_service import _specialties_size_class


def test_short_line_keeps_base_size():
    assert _specialties_size_class('Алергологія') == 'cert__meta-line--md'


def test_long_line_gets_smaller_class():
    line = ', '.join(['Дитяча кардіоревматологія'] * 6)
    assert _specialties_size_class(line) == 'cert__meta-line--xs'


def test_empty_line_is_md():
    assert _specialties_size_class('') == 'cert__meta-line--md'
```

Додати сюди ж тест знімка (потребує фікстур курсу, проведення й реєстрації -- узяти зі списку наявних тестів сертифікатів у `tests/test_services/`): знімок береться з ефективного списку проведення, і перейменування рядка довідника після видачі його НЕ змінює.

- [ ] **Step 2: Запустити тести й переконатись, що падають**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_certificate_specialties.py -v`
Expected: FAIL -- `ImportError: cannot import name '_specialties_size_class'`

- [ ] **Step 3: Додати клас розміру**

У `app/services/certificate_service.py` після `_event_size_class` (рядок 352-364):

```python
def _specialties_size_class(text):
    """Адаптивний розмір рядка «Спеціальності:» у метаблоці.

    Ліміту на кількість обраних спеціальностей немає, тож довгий перелік
    інакше виштовхнув би метаблок за межі тіла сертифіката.
    """
    n = len(text or '')
    if n <= 90:
        return 'cert__meta-line--md'
    if n <= 180:
        return 'cert__meta-line--sm'
    return 'cert__meta-line--xs'
```

і в контекст рендеру (поруч із рядком 454):

```python
        specialties_size_class=_specialties_size_class(
            getattr(certificate, 'specialties', None)),
```

- [ ] **Step 4: Додати класи в шаблони сертифікатів**

У `app/templates/certificates/certificate.html` поруч із розмірами назви заходу (рядки 108-112):

```css
  .cert__meta-line--md { font-size: 10pt; }
  .cert__meta-line--sm { font-size: 9pt; }
  .cert__meta-line--xs { font-size: 8pt; }
```

(значення звірити з поточним `font-size` у `.cert__meta p`, рядок 93: `--md` має дорівнювати йому.)

Рядок 197 замінити на:

```html
          {% if specialties %}<p class="{{ specialties_size_class }}">Спеціальності: {{ specialties }}</p>{% endif %}
```

Те саме -- у `app/templates/certificates/certificate_compact.html` (стилі біля рядка 121, рядок 210).

- [ ] **Step 5: Перевести демо-дані прев'ю**

У `app/admin/routes_tools.py` рядки 59 і 66 містять демо-рядок `'усі лікарські спеціальності'`. Замінити на значення, отримане з довідника:

```python
    demo_specialties = specialties_service.line(['all-medical']) or 'усі лікарські спеціальності'
```

і підставляти `demo_specialties` замість літерала. Імпорт: `from app.services import specialties as specialties_service`.

- [ ] **Step 6: Запустити тести**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_certificate_specialties.py -v`
Expected: PASS

- [ ] **Step 7: Подивитись на сертифікат очима**

Відкрити `/admin/tools/certificate-preview` (шлях звірити в `routes_tools.py`) і переконатись: рядок з однією спеціальністю виглядає як раніше, рядок із шести назв не виходить за межі метаблоку.

- [ ] **Step 8: Коміт**

```bash
git add app/services/certificate_service.py app/templates/certificates app/admin/routes_tools.py tests/test_services/test_certificate_specialties.py
git commit -m "feat(certificates): рядок спеціальностей із довідника і його розмір

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Фінальна перевірка й чекліст деплою

**Files:**
- Modify: `README.md` (розділ про довідники адмінки -- додати «Довідник спеціальностей»)
- Create: нічого

**Interfaces:**
- Consumes: усе попереднє.
- Produces: підтвердження, що набір зелений, і перелік кроків деплою.

- [ ] **Step 1: Прогнати весь набір тестів**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Падіння в чужих тестах через залишених користувачів (`test_api_v1_clients`) означає, що фікстура нової задачі не прибрала за собою.

- [ ] **Step 2: Перевірити дизайн-систему числами і знімками**

```bash
./venv/Scripts/python.exe tools/ds/ds_audit.py
./venv/Scripts/python.exe tools/ds/html_snapshot.py
```

Expected: без нових дублів класів; знімки показують зміни лише на сторінках курсу, проведення, вітрини і нового довідника.

- [ ] **Step 3: Дописати README**

У розділ про адмінку додати рядок про `/admin/specialties`: що це чинна номенклатура для рядка «Спеціальності:» у сертифікаті, що зайнятий рядок деактивують, а не видаляють, і що первинне наповнення робиться `tools/parse_specialties.py`.

- [ ] **Step 4: Коміт**

```bash
git add README.md
git commit -m "docs: довідник спеціальностей у README

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Скласти чекліст деплою для користувача**

Віддати користувачеві списком, НЕ виконуючи самому:

1. `flask db upgrade` на проді (ревізія `specialties_20260909`; вона ж сіє довідник і переносить наявні значення).
2. `flask rbac sync` -- інакше право `specialties.*` не з'явиться в матриці.
3. `/admin/access` -- роздати `specialties.view`/`.manage` тим ролям, яким треба (автоматично його має лише `super_admin`).
4. Відкрити `/admin/specialties` і перевірити рядки з `is_active=False`: туди міграція поклала значення, яких не було в номенклатурі.
5. Перевірити пару курсів у `/admin/courses`: вибір підтягнувся, сертифікат-прев'ю друкує той самий рядок, що й до деплою.

---

## Самоперевірка плану

Звірено зі спекою:

- обсяг розділів I-IV і виняток для «профілів роботи» -- Задача 1;
- узагальнення рядками довідника -- Задача 3 (сид міграції);
- рендер через кому без ліміту -- Задача 2 (`line`) і Задача 6 (розмір рядка);
- перевизначення на рівні проведення -- Задача 3 (`effective_specialty_codes`);
- `<select multiple>` + прогресивне покращення -- Задача 4;
- перекладність назв через `TranslatableMixin` і зняття поля з `Course.__translatable__` / `FIELD_LABELS` -- Задачі 2 і 3;
- знімок сертифіката рядком і перехід у `Text` -- Задача 3;
- пастка `choices` із деактивованим кодом -- Задача 3, крок 9, і тест у кроці 14;
- сторінка довідника, права, сайдбар, `flask rbac sync` -- Задача 5 і чекліст у Задачі 7;
- картка компонента у вітрині -- Задача 4, крок 4.

Відоме місце, де план свідомо просить ітерацію: розбір PDF (Задача 1, крок 7). Правила розбору написані за спостереженою структурою тексту, але дамп `pypdf` міг зберегти й інші переноси; перевірка послідовності номерів у підрозділі це виявить, і крок прямо каже правити правила, доки зауважень не лишиться.
