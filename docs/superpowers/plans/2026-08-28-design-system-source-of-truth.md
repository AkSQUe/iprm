# Дизайн-система як джерело істини (Етап 1) — план реалізації

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** зробити дизайн-систему перевіреним джерелом істини: каталог живе в адмінці, підключає всі компонентні CSS, а два сторожі не дають з'явитись новому дублікату компонента.

**Architecture:** Каталог переїжджає з публічного `main.design_system` на `admin.design_system` (шаблон на `base_admin.html`), вміст ділиться на п'ять партіалів під табами `iprm-tabs`. Новий постійний інструмент `tools/ds/ds_audit.py` дає числа концепту; два pytest-сторожі фіксують інваріанти, причому дублікати тримає храповик із baseline-файлу. Кожна правка перевіряється наявним `tools/ds/html_snapshot.py` (77 сторінок, шум нуль).

**Tech Stack:** Flask 3 + Jinja2, pytest, vanilla JS/CSS без збірок. Жодних нових залежностей.

**Spec:** [docs/superpowers/specs/2026-08-28-design-system-source-of-truth-design.md](../specs/2026-08-28-design-system-source-of-truth-design.md)

## Global Constraints

Ці вимоги діють у КОЖНОМУ завданні; окремо в кроках не повторюються.

- Жодних inline `style=` і `<script>` у шаблонах. Виняток — PDF (`certificates/`, `invoices/`, `main/offer_pdf.html`), листи (`emails/`) і анти-флікер-шими в `base.html` / `base_admin.html`.
- `!important` не використовувати.
- Кожен `<link>` на статику несе `?v={{ assets_version }}`.
- Жодних emoji в коді.
- Захардкоджений колір/радіус/тінь заборонені — тільки `var(--iprm-*)`. Текст на акцентному фоні — `--iprm-on-accent`, не `--iprm-white` (у темній темі він темна поверхня, `common.css:186`).
- Іконки — лише через глобал `icon('name')`.
- **Коміт лише на явну команду користувача, пуш — на окрему.** Кроки «Commit» у плані показують, ЩО і ЯКИМ повідомленням комітити, коли команду дадуть. Ніколи `git add -A` — тільки явні шляхи.
- Тести запускати з `PYTHONIOENCODING=utf-8` (консоль Windows інакше калічить кирилицю у виводі).
- Знімок розмітки: `python tools/ds/html_snapshot.py capture --label before` до правок, `--label after` після, `diff before after` — і кожну розбіжність пояснити.

---

## Порядок і чому саме такий

Спершу інструмент і сторожі (Задачі 1-2), бо далі вони ловитимуть помилки самої роботи. Потім переїзд (3) і таби (4) — вони змінюють лише сторінку каталогу. Далі підключення 40 файлів (5), яке має сенс лише коли каталог уже на місці. Перейменування (6) — останнім із коду, під знімком. Документація (7) — після того, як усе працює, щоб описувати факт, а не намір.

---

### Task 1: `ds_audit.py` — числа концепту

**Files:**
- Create: `tools/ds/ds_audit.py`
- Create: `tests/test_design_system/test_ds_audit.py`
- Modify: `tools/ds/README.md`

**Interfaces:**
- Produces: `classify_css(root=ROOT) -> dict` з ключами `component: dict[str, int]` (ім'я файлу -> кількість споживачів), `page: dict[str, int]`, `unresolved: list[str]`; `duplicate_classes(root=ROOT) -> dict[str, list[str]]` (клас -> відсортований список файлів, лише де файлів 2+); `catalog_gap(root=ROOT) -> list[str]`; `naming_mismatch(root=ROOT) -> dict` з ключами `should_lose_prefix: list[str]`, `should_gain_prefix: list[str]`. Усі чотири приймають корінь репозиторію єдиним позиційним аргументом.
- Задачі 2, 3, 5 і 6 імпортують саме ці чотири функції. Імена не змінювати.

**Чому інструмент, а не разовий скрипт:** ці числа перевіряються на кожному наступному проході, а не один раз. Дисципліна така сама, як у `tools/perf/perf_check.py`: інструмент у git, вивід у `.gitignore`.

- [ ] **Step 1: Написати тест на транзитивний підрахунок споживачів**

Це головна пастка правила: CSS, підключений із партіала, має «одного споживача» — сам партіал, — хоча партіал інклюдять багато шаблонів.

```python
# tests/test_design_system/test_ds_audit.py
"""ds_audit рахує споживачів CSS транзитивно -- через include і extends.

Наївний підрахунок дає хибний результат: material-symbols.css підключений
з partials/_icon_font.html, тобто прямих споживачів у нього один, хоча
партіал інклюдить base_admin.html, який розширюють усі сторінки адмінки.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'ds'))

import ds_audit


def test_css_from_partial_counts_transitively():
    result = ds_audit.classify_css(ROOT)
    assert 'material-symbols.css' in result['component'], (
        'material-symbols.css підключений з partials/_icon_font.html, який '
        'інклюдить admin/base_admin.html -- це компонентний файл, а не '
        'посторінковий. Схоже, підрахунок споживачів не транзитивний.'
    )
    assert result['component']['material-symbols.css'] > 1


def test_page_only_css_stays_page():
    result = ds_audit.classify_css(ROOT)
    assert 'page-contact.css' in result['page']
    assert result['page']['page-contact.css'] == 1


def test_duplicate_classes_finds_apple_btn():
    dupes = ds_audit.duplicate_classes(ROOT)
    assert 'apple-btn' in dupes, (
        'apple-btn переоголошений у кількох сторінкових файлах -- саме той '
        'випадок, коли правка кнопки в дизайн-системі до сторінки не доходить.'
    )
    assert len(dupes['apple-btn']) >= 2
```

- [ ] **Step 2: Запустити тест — має впасти**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_design_system/test_ds_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ds_audit'`

- [ ] **Step 3: Написати `tools/ds/ds_audit.py`**

Ключові рішення, які треба зберегти:
- граф шаблонів будується з `{% extends '...' %}` і `{% include '...' %}` зі **строковими літералами**; динамічний include (змінна замість рядка) — не мовчазний пропуск, а рядок у звіті `unresolved`, інакше файл тихо недорахує споживачів;
- `_content.html` каталогу з підрахунку споживачів виключається окремо: він показує компоненти, а не вживає їх, інакше кожен показаний клас робив би свій файл «компонентним» сам собою;
- коментарі з CSS вирізаються ДО розбору селекторів.

```python
#!/usr/bin/env python
"""Числа концепту "дизайн-система -- джерело істини".

Відповідає на чотири питання:
  1. які CSS-файли компонентні, а які посторінкові (і скільки в кого споживачів);
  2. які класи оголошені більш ніж в одному файлі -- саме там правка
     дизайн-системи до сторінки НЕ доходить;
  3. які компонентні файли не підключені до каталогу;
  4. чиє ім'я суперечить суті (page-* у компонента і навпаки).

Межа: файл компонентний, якщо має 2+ шаблони-споживачі. Споживачі
рахуються ТРАНЗИТИВНО -- через extends і include: CSS із партіала має
одного прямого споживача (сам партіал), хоча партіал інклюдять десятки
сторінок.

Використання:
    python tools/ds/ds_audit.py                # повний звіт
    python tools/ds/ds_audit.py --write-baseline
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'tests' / 'test_design_system' / 'duplicate_classes_baseline.json'

# Шаблон каталогу ПОКАЗУЄ компоненти, а не вживає їх: інакше кожен показаний
# клас робив би свій файл компонентним сам собою.
CATALOG_GLOBS = ('design_system/*.html', 'admin/design_system*.html')

_EXTENDS = re.compile(r"{%-?\s*extends\s+['\"]([^'\"]+)['\"]")
_INCLUDE = re.compile(r"{%-?\s*include\s+['\"]([^'\"]+)['\"]")
_INCLUDE_DYNAMIC = re.compile(r"{%-?\s*include\s+(?!['\"])")
_CSS_LINK = re.compile(r"filename=['\"]css/([\w.-]+\.css)['\"]")
_COMMENT = re.compile(r'/\*.*?\*/', re.S)


def _templates(root):
    tpl = root / 'app' / 'templates'
    return {
        p.relative_to(tpl).as_posix(): p.read_text(encoding='utf-8', errors='ignore')
        for p in tpl.rglob('*.html')
    }


def _catalog_names(root):
    tpl = root / 'app' / 'templates'
    names = set()
    for pattern in CATALOG_GLOBS:
        for p in tpl.glob(pattern):
            names.add(p.relative_to(tpl).as_posix())
    return names


def classify_css(root=ROOT):
    """{'component': {файл: споживачів}, 'page': {...}, 'unresolved': [...]}"""
    texts = _templates(root)
    catalog = _catalog_names(root)

    direct = {name: set(_CSS_LINK.findall(text)) for name, text in texts.items()}
    parents = {}
    for name, text in texts.items():
        refs = set(_EXTENDS.findall(text)) | set(_INCLUDE.findall(text))
        parents[name] = {r for r in refs if r in texts}

    unresolved = [n for n, t in texts.items() if _INCLUDE_DYNAMIC.search(t)]

    def effective(name, seen=None):
        seen = seen or set()
        if name in seen:
            return set()
        seen.add(name)
        out = set(direct.get(name, ()))
        for parent in parents.get(name, ()):
            out |= effective(parent, seen)
        return out

    counts = {}
    for name in texts:
        if name in catalog:
            continue
        for css in effective(name):
            counts[css] = counts.get(css, 0) + 1

    for css_file in (root / 'app' / 'static' / 'css').glob('*.css'):
        counts.setdefault(css_file.name, 0)

    component = {k: v for k, v in sorted(counts.items()) if v > 1}
    page = {k: v for k, v in sorted(counts.items()) if v <= 1}
    return {'component': component, 'page': page, 'unresolved': sorted(unresolved)}


def _declared_classes(path):
    css = _COMMENT.sub(' ', path.read_text(encoding='utf-8'))
    names = set()
    for head in re.findall(r'([^{}]+)\{', css):
        if head.lstrip().startswith('@'):
            continue
        names |= set(re.findall(r'\.([a-zA-Z][\w-]*)', head))
    return names


def duplicate_classes(root=ROOT):
    """{клас: [файли]} для класів, оголошених у 2+ файлах."""
    owners = {}
    for path in sorted((root / 'app' / 'static' / 'css').glob('*.css')):
        for cls in _declared_classes(path):
            owners.setdefault(cls, set()).add(path.name)
    return {c: sorted(f) for c, f in sorted(owners.items()) if len(f) > 1}


def catalog_gap(root=ROOT):
    """Компонентні файли, яких каталог не підключає."""
    tpl = root / 'app' / 'templates'
    linked = set()
    for name in _catalog_names(root):
        linked |= set(_CSS_LINK.findall((tpl / name).read_text(encoding='utf-8')))
    # Каталог розширює base_admin.html -> отримує все, що той тягне.
    texts = _templates(root)
    for name in _catalog_names(root):
        for ref in set(_EXTENDS.findall(texts[name])) | set(_INCLUDE.findall(texts[name])):
            if ref in texts:
                linked |= set(_CSS_LINK.findall(texts[ref]))
                for ref2 in set(_EXTENDS.findall(texts[ref])) | set(_INCLUDE.findall(texts[ref])):
                    if ref2 in texts:
                        linked |= set(_CSS_LINK.findall(texts[ref2]))
    return sorted(set(classify_css(root)['component']) - linked)


def naming_mismatch(root=ROOT):
    result = classify_css(root)
    return {
        'should_lose_prefix': sorted(n for n in result['component'] if n.startswith('page-')),
        'should_gain_prefix': sorted(
            n for n in result['page']
            if not n.startswith('page-') and result['page'][n] == 1
        ),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--write-baseline', action='store_true',
                    help='перезаписати baseline дублікатів (лише коли він ЗМЕНШУЄТЬСЯ)')
    args = ap.parse_args()

    kinds = classify_css()
    dupes = duplicate_classes()
    gap = catalog_gap()
    naming = naming_mismatch()

    print('КОМПОНЕНТНИХ ФАЙЛІВ: %d' % len(kinds['component']))
    print('ПОСТОРІНКОВИХ:       %d' % len(kinds['page']))
    if kinds['unresolved']:
        print('  УВАГА: динамічний include у %d шаблонах, споживачі недораховані: %s'
              % (len(kinds['unresolved']), ', '.join(kinds['unresolved'][:5])))
    print('\nДУБЛІКАТИ (клас у 2+ файлах): %d' % len(dupes))
    for cls, files in list(dupes.items())[:10]:
        print('   .%-28s %s' % (cls, ', '.join(files)))
    if len(dupes) > 10:
        print('   ... ще %d' % (len(dupes) - 10))
    print('\nКОМПОНЕНТНІ ФАЙЛИ ПОЗА КАТАЛОГОМ: %d' % len(gap))
    for name in gap:
        print('   ' + name)
    print('\nІМ\'Я СУПЕРЕЧИТЬ СУТІ: %d'
          % (len(naming['should_lose_prefix']) + len(naming['should_gain_prefix'])))
    for name in naming['should_lose_prefix']:
        print('   %-34s компонентний, але з префіксом page-' % name)
    for name in naming['should_gain_prefix']:
        print('   %-34s посторінковий, але без префікса' % name)

    if args.write_baseline:
        old = json.loads(BASELINE.read_text(encoding='utf-8')) if BASELINE.exists() else {}
        if len(dupes) > len(old or {}):
            print('\nВІДМОВА: дублікатів стало БІЛЬШЕ (%d проти %d). Baseline '
                  'може лише зменшуватись.' % (len(dupes), len(old)))
            return 1
        BASELINE.write_text(
            json.dumps(dupes, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
            encoding='utf-8')
        print('\nbaseline записано: %d класів -> %s' % (len(dupes), BASELINE))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Запустити тести — мають пройти**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_design_system/test_ds_audit.py -v`
Expected: PASS, 3 тести.

- [ ] **Step 5: Прогнати сам аудит і звірити числа зі спекою**

Run: `PYTHONIOENCODING=utf-8 python tools/ds/ds_audit.py`

Заміряно фактично: компонентних 40, посторінкових 26, дублікатів **69**, компонентних поза каталогом **25**, розбіжностей імені й суті **19** (плюс design-system.css, якого інструмент не бачить -- пояснення в Задачі 6).

**Якщо число дублікатів не 69 — зупинитись і розібратись, а не підганяти.** Метрика рахує клас оголошеним лише в СУБ'ЄКТІ правила: `.link:has(.badge)` не робить `.badge` власністю файлу, а `.page .badge {}` -- робить. Розбіжність означає, що розбір селектора змінився.

- [ ] **Step 6: Записати baseline**

Run: `PYTHONIOENCODING=utf-8 python tools/ds/ds_audit.py --write-baseline`
Expected: `baseline записано: 69 класів`.

- [ ] **Step 7: Дописати README і .gitignore**

У `tools/ds/README.md` додати розділ про `ds_audit.py` за зразком наявного розділу про `html_snapshot.py`: що міряє, які числа сьогодні, чому інструмент у git. Вивід аудиту в файли не пишеться, тож `.gitignore` правити не треба — baseline лежить у `tests/` і комітиться навмисно.

- [ ] **Step 8: Commit**

```bash
git add tools/ds/ds_audit.py tools/ds/README.md tests/test_design_system/test_ds_audit.py tests/test_design_system/duplicate_classes_baseline.json
git commit -m "feat(design-system): інструмент, що міряє, де правка стилю не доходить до сторінки"
```

---

### Task 2: Храповик дублікатів

**Files:**
- Create: `tests/test_design_system/test_component_ownership.py`

**Interfaces:**
- Consumes: `ds_audit.duplicate_classes`, `tests/test_design_system/duplicate_classes_baseline.json` (Task 1).

**Чому храповик, а не «нуль дублікатів»:** сьогодні їх 69, і закриття — робота Етапів 2-3. Тест, який падає одразу, вимкнуть. Тест, який падає лише на **новому** дублікаті, зупиняє регрес і не заважає.

- [ ] **Step 1: Написати тест**

```python
# tests/test_design_system/test_component_ownership.py
"""Компонент оголошується один раз -- інакше правка до сторінки не доходить.

Клас, оголошений у двох файлах, перебивається тим, що підключений пізніше.
Саме через це правка `apple-btn` у дизайн-системі сьогодні не змінює кнопку
на /courses: page-courses.css переоголошує її в себе.

Тест -- ХРАПОВИК, а не вимога нуля: 69 наявних дублікатів закриваються
окремими етапами, а тест не дає з'явитись 81-му. Коли дублікат прибрано,
baseline перезаписується `python tools/ds/ds_audit.py --write-baseline`;
інструмент відмовиться це зробити, якщо число зросло.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'ds'))

import ds_audit

BASELINE = Path(__file__).parent / 'duplicate_classes_baseline.json'


def test_no_new_duplicate_classes():
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    current = ds_audit.duplicate_classes(ROOT)
    fresh = sorted(set(current) - set(baseline))
    assert not fresh, (
        'нові класи з двома власниками: ' + ', '.join(
            '.%s (%s)' % (c, ', '.join(current[c])) for c in fresh)
        + '\nКомпонент мусить бути оголошений ОДИН раз -- інакше правка в '
          'дизайн-системі не дійде до сторінки, що його переоголосила. '
          'Візьміть наявний компонент (перелік -- на /admin/design-system) '
          'або винесіть свій у компонентний файл.'
    )


def test_baseline_only_shrinks():
    """Прибрали дублікат -- перезапишіть baseline; він не має рости."""
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    current = ds_audit.duplicate_classes(ROOT)
    assert len(current) <= len(baseline), (
        'дублікатів стало більше: %d проти %d у baseline'
        % (len(current), len(baseline))
    )
```

- [ ] **Step 2: Запустити — має пройти на поточному коді**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_design_system/test_component_ownership.py -v`
Expected: PASS (2 тести).

- [ ] **Step 3: Перевірити зуби — тест мусить ловити новий дублікат**

Тимчасово додати в `app/static/css/page-contact.css` наприкінці файла:

```css
.admin-empty {
  color: var(--iprm-text);
}
```

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_design_system/test_component_ownership.py -v`
Expected: FAIL зі згадкою `.admin-empty (admin.css, page-contact.css)`.

**Прибрати правило після перевірки** і переконатись, що тест знову зелений. Без цієї перевірки невідомо, чи тест взагалі щось ловить.

- [ ] **Step 4: Commit**

```bash
git add tests/test_design_system/test_component_ownership.py
git commit -m "test(design-system): храповик, що не дає з'явитись другому власнику класу"
```

---

### Task 3: Каталог переїжджає в адмінку

**Files:**
- Create: `app/admin/routes_design_system.py`
- Create: `app/templates/admin/design_system.html`
- Modify: `app/admin/routes.py` (додати рядок імпорту)
- Modify: `app/main/routes.py:233-235` (перетворити на редирект)
- Modify: `app/templates/admin/partials/_sidebar.html` (пункт у групі «Система»)
- Modify: `app/icons.py` (через `scripts/subset-icons.py`, не руками)

**Interfaces:**
- Produces: ендпоінт `admin.design_system` за адресою `/admin/design-system`.

На цьому кроці вміст НЕ ділиться і таби НЕ додаються — переїзд окремо від переверстки, щоб при розбіжності було зрозуміло, від чого.

- [ ] **Step 1: Зняти знімок ДО**

Run: `PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py capture --label before`
Expected: `77 сторінок`.

- [ ] **Step 2: Написати тест на доступ і місце**

```python
# tests/test_design_system/test_catalog_route.py
"""Каталог живе в адмінці, під логіном, і має вихід зі старої адреси."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.user import User


@pytest.fixture
def admin():
    # Email унікальний: тести ділять сесію додатка, і фіксована адреса
    # зіткнулась би з unique-індексом users.email у сусідньому тесті.
    u = User.create_with_password(
        f'ds-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_catalog_requires_admin(client):
    resp = client.get('/admin/design-system')
    assert resp.status_code in (302, 401, 403)


def test_catalog_renders_for_admin(client, admin):
    _login(client, admin)
    resp = client.get('/admin/design-system')
    assert resp.status_code == 200
    assert 'ds-section' in resp.get_data(as_text=True)


def test_old_public_url_redirects(client):
    resp = client.get('/design-system')
    assert resp.status_code in (301, 302)
    assert '/admin/design-system' in resp.headers['Location']
```

Фікстура `client` — з `tests/conftest.py`. Фікстури `admin_client` у проєкті **немає**; спосіб логіну вище скопійований із `tests/test_i18n/test_translation_editor.py:14-27` — це наявний патерн, і відхилятись від нього не треба. Відкат робить autouse-фікстура `db_session`.

- [ ] **Step 3: Запустити — має впасти**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_design_system/test_catalog_route.py -v`
Expected: FAIL — 404 на `/admin/design-system`.

- [ ] **Step 4: Створити роут**

```python
# app/admin/routes_design_system.py
"""Admin: каталог дизайн-системи.

Каталог показує компоненти ЖИВИМИ -- підключає ті самі CSS-файли, з яких
малюються справжні сторінки. Тому він ламається разом із компонентом, якщо
той зламали, і тёмна тема перевіряється сама собою.

Жив на публічному /design-system із noindex; переїхав в адмінку, бо це
інструмент розробки, а не сторінка сайту. Стара адреса лишилась редиректом.
"""
from flask import render_template

from app.admin import admin_bp
from app.admin.decorators import admin_required


@admin_bp.route('/design-system')
@admin_required
def design_system():
    return render_template('admin/design_system.html')
```

У `app/admin/routes.py` дописати рядком у той самий блок імпортів:

```python
from app.admin import routes_design_system  # noqa: F401
```

- [ ] **Step 5: Створити шаблон**

```html
{# app/templates/admin/design_system.html #}
{% extends 'admin/base_admin.html' %}

{% block title %}Дизайн-система | ІПРМ Admin{% endblock %}

{% block extra_css %}
  {{ super() }}
  <link rel="stylesheet" href="{{ url_for('static', filename='css/admin.css') }}?v={{ assets_version }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/page-admin-design-system.css') }}?v={{ assets_version }}">
  {# Секції показують компоненти живими, а не мокапом з інлайн-стилів:
     так каталог ламається разом із компонентом. apple-pages.css --
     залежність course-landing.css (обидва скоуплені на .apple-page). #}
  <link rel="stylesheet" href="{{ url_for('static', filename='css/apple-pages.css') }}?v={{ assets_version }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/course-landing.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
  {% include 'admin/partials/_sidebar.html' %}
  <main class="admin-main">
    {% include 'design_system/_content.html' %}
  </main>
{% endblock %}
```

**Перед написанням цього блоку — відкрити дві сусідні адмін-сторінки** (`app/templates/admin/perf_runs.html` і `app/templates/admin/settings.html`) і повторити їхню структуру блоків точно: чи є `{{ super() }}` в `extra_css`, як саме інклюдиться сайдбар, у який елемент загорнутий вміст. Розбіжність тут дасть з'їхалу верстку, якої знімок не побачить (він порівнює HTML, а не вигляд).

- [ ] **Step 6: Пункт у сайдбарі**

У `app/templates/admin/partials/_sidebar.html`, у групі «Система», відразу після пункту «Швидкість сторінок»:

```html
      <a href="{{ url_for('admin.design_system') }}" class="admin-sidebar__link{% if ep == 'admin.design_system' %} admin-sidebar__link--active{% endif %}">
        {{ icon('palette') }}
        <span class="admin-sidebar__text">Дизайн-система</span>
      </a>
```

- [ ] **Step 7: Додати іконку в субсет**

Run: `python scripts/subset-icons.py`

Скрипт сам знаходить `icon('palette')` у шаблонах, тягне кодпойнт із кешованого офіційного списку і перезаписує блок `ICON_CODEPOINTS` у `app/icons.py` плюс `app/static/fonts/material-symbols-rounded.woff2`. **Кодпойнт руками не вписувати.**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_icons.py -v`
Expected: PASS.

- [ ] **Step 8: Стару адресу — в редирект**

`app/main/routes.py:233-235` замінити на:

```python
@main_bp.route('/design-system', localize=False)
def design_system():
    """Каталог переїхав в адмінку. Редирект -- щоб не ламались закладки
    й посилання в docs/; сам каталог тепер під admin_required.

    302, а не 301: сторінка noindex, SEO-ваги передавати нема чого, а
    постійний редирект браузер кешує назавжди -- відкотити переїзд на вже
    відвіданих машинах було б неможливо."""
    return redirect(url_for('admin.design_system'), code=302)
```

Переконатись, що `redirect` і `url_for` вже імпортовані у файлі (`grep -n "^from flask import" app/main/routes.py`). Рядок `Disallow: /design-system` у `robots.txt`-роуті **лишити**.

- [ ] **Step 9: Запустити тести**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_design_system/ tests/test_icons.py -v`
Expected: PASS.

- [ ] **Step 10: Знімок ПІСЛЯ і пояснення кожної розбіжності**

Run:
```
PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py capture --label after
PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py diff before after
```

Очікується рівно три зміни, і жодної іншої:
- `main.design_system.html` **зник** (тепер 301, у знімок не потрапляє);
- `admin.design_system.html` **з'явився**;
- усі сторінки адмінки змінились **на один рядок** — новий пункт сайдбару.

Будь-яка четверта розбіжність — зупинка й розбір. Розбіжність на публічних сторінках означає, що правка зачепила `base.html`, чого тут не планувалось.

- [ ] **Step 11: Commit**

```bash
git add app/admin/routes_design_system.py app/admin/routes.py app/templates/admin/design_system.html app/templates/admin/partials/_sidebar.html app/main/routes.py app/icons.py app/static/fonts/material-symbols-rounded.woff2 tests/test_design_system/test_catalog_route.py
git commit -m "feat(design-system): каталог переїхав в адмінку, публічна адреса лишилась редиректом"
```

---

### Task 4: Таби і розділення вмісту

**Files:**
- Create: `app/templates/design_system/_tab_foundation.html`
- Create: `app/templates/design_system/_tab_atoms.html`
- Create: `app/templates/design_system/_tab_molecules.html`
- Create: `app/templates/design_system/_tab_admin.html`
- Create: `app/templates/design_system/_tab_rules.html`
- Delete: `app/templates/design_system/_content.html`
- Delete: `app/templates/design_system/index.html`
- Modify: `app/templates/admin/design_system.html`
- Modify: `tests/test_design_system/test_catalog_coverage.py:23` (шлях до вітрини)

**Interfaces:**
- Consumes: `admin.design_system` (Task 3).
- Produces: п'ять партіалів; `test_catalog_coverage.py` читає їх усі замість одного `_content.html`.

**Компонент табів ще ніхто не вмикав.** `iprm-tabs` (`tabs.css` + `tabs.js`) вантажиться глобально з `base.html`, але розмітки `data-iprm-tabs` немає в жодному шаблоні — нуль споживачів. Каталог стане першим, тож роботу компонента треба **перевірити**, а не припустити.

- [ ] **Step 1: Знімок ДО**

Run: `PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py capture --label before`

- [ ] **Step 2: Розрізати `_content.html` за межами секцій**

Межі (номери рядків у поточному `_content.html`):

| Партіал | Секції | Рядки |
|---|---|---|
| `_tab_foundation.html` | pages, colors, typography, spacing, animations | 2-179, 259-304, 797-868, 1074-1103 |
| `_tab_atoms.html` | primitives, buttons, badges, alerts, form-section, empty-state | 180-258, 305-423, 720-762, 780-796 |
| `_tab_molecules.html` | hero, feature-cards, bento, stats, clinic-cards, course-cards, target, trainer, program, cta, about, content-page, cookie-banner, footer, course-landing | 424-719, 763-779, 1057-1073, 1528-1749 |
| `_tab_admin.html` | admin | 1104-1527 |
| `_tab_rules.html` | accessibility, responsive, performance, modern-css | 869-1015, 1016-1056 |

**Різати копіюванням, не переписуванням.** Тексти підказок, заголовків і порожніх станів беруться з файлу як є: одна описка тихо змінить те, що бачить читач каталогу.

Діапазони вище покривають рядки 2-1749 суцільно й без перекриття — це перевірено при складанні плану. Порядок склеювання всередині партіала — за зростанням номерів рядків. Після розрізання: `wc -l` п'яти партіалів мінус рядки обгорток мусить дати 1748, і жодна секція не має загубитись — це ловить тест покриття на кроці 5.

- [ ] **Step 3: Зібрати таби в `admin/design_system.html`**

Розмітка — рівно та, яку читає `tabs.js` (див. його докстрінг: `data-iprm-tabs`, `data-tab-trigger`, `data-tab-panel`, `data-tab-default`):

```html
{% block content %}
  {% include 'admin/partials/_sidebar.html' %}
  <main class="admin-main">
    <div class="iprm-tabs" data-iprm-tabs>
      <div class="iprm-tabs__list" role="tablist" aria-label="Розділи дизайн-системи">
        <button type="button" class="iprm-tabs__trigger" data-tab-trigger="foundation" data-tab-default>Основа</button>
        <button type="button" class="iprm-tabs__trigger" data-tab-trigger="atoms">Атоми</button>
        <button type="button" class="iprm-tabs__trigger" data-tab-trigger="molecules">Молекули</button>
        <button type="button" class="iprm-tabs__trigger" data-tab-trigger="admin">Адмінка</button>
        <button type="button" class="iprm-tabs__trigger" data-tab-trigger="rules">Правила</button>
      </div>
      <div class="iprm-tabs__panel" data-tab-panel="foundation">{% include 'design_system/_tab_foundation.html' %}</div>
      <div class="iprm-tabs__panel" data-tab-panel="atoms">{% include 'design_system/_tab_atoms.html' %}</div>
      <div class="iprm-tabs__panel" data-tab-panel="molecules">{% include 'design_system/_tab_molecules.html' %}</div>
      <div class="iprm-tabs__panel" data-tab-panel="admin">{% include 'design_system/_tab_admin.html' %}</div>
      <div class="iprm-tabs__panel" data-tab-panel="rules">{% include 'design_system/_tab_rules.html' %}</div>
    </div>
  </main>
{% endblock %}
```

Стару навігацію-якорі з `design_system/index.html` (30 посилань `#anchor`) не переносити: її замінюють таби. Сам `index.html` видалити разом із `_content.html`.

- [ ] **Step 4: Полагодити тест покриття**

У `tests/test_design_system/test_catalog_coverage.py` константа `SHOWCASE` вказує на `design_system/_content.html`, якого більше немає. Замінити на читання всіх п'яти партіалів:

```python
SHOWCASE_DIR = ROOT / 'app' / 'templates' / 'design_system'


def _showcase_text():
    return '\n'.join(
        p.read_text(encoding='utf-8') for p in sorted(SHOWCASE_DIR.glob('_tab_*.html'))
    )
```

і скрізь, де було `SHOWCASE.read_text(encoding='utf-8')`, підставити `_showcase_text()`.

- [ ] **Step 5: Запустити тести**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_design_system/ -v`
Expected: PASS, зокрема всі 74 параметризовані перевірки покриття — жоден клас не має загубитись при розрізанні. Це і є головний захист кроку: якщо секція випала, тест назве конкретний клас.

- [ ] **Step 6: Перевірити таби живцем**

Знімок HTML не бачить, чи працює JS. Відрендерити сторінку в браузері (`flask run` не потрібен — досить `python tools/ds/html_snapshot.py capture --label tabs` і відкрити збережений файл, або підняти застосунок локально) і перевірити чотири речі:

1. відкривається таб «Основа», решта панелей приховані;
2. клік по кожному тригеру перемикає панель;
3. стрілки Left/Right ходять по табах, Home/End — на крайні;
4. `aria-selected` міняється, панель має `role="tabpanel"`.

Якщо щось із цього не працює — **лагодити `tabs.js`, а не обходити своєю розміткою**: компонент уперше отримав споживача, і його вади треба закрити в ньому.

- [ ] **Step 7: Знімок ПІСЛЯ**

Run: `PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py diff before after` (після `capture --label after`)
Expected: рівно одна сторінка з розбіжністю — `admin.design_system.html`. Це видима зміна, і вона навмисна.

- [ ] **Step 8: Commit**

```bash
git add app/templates/design_system/ app/templates/admin/design_system.html tests/test_design_system/test_catalog_coverage.py
git commit -m "refactor(design-system): каталог на 1749 рядків розкладено по п'яти табах"
```

---

### Task 5: Каталог підключає всі компонентні файли

**Files:**
- Modify: `app/templates/admin/design_system.html` (блок `extra_css`)
- Create: `tests/test_design_system/test_catalog_links_components.py`
- Modify: `app/templates/design_system/_tab_rules.html` (розділ про обмеження)

**Interfaces:**
- Consumes: `ds_audit.catalog_gap` (Task 1).

- [ ] **Step 1: Написати тест**

```python
# tests/test_design_system/test_catalog_links_components.py
"""Каталог мусить підключати КОЖЕН компонентний CSS.

Інакше компонент неможливо побачити на вітрині -- а невидимий компонент
переписують у себе. Межа: файл компонентний, якщо має 2+ шаблони-споживачі
(транзитивно, через include/extends) -- див. tools/ds/ds_audit.py.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'ds'))

import ds_audit


def test_every_component_css_is_linked_in_catalog():
    gap = ds_audit.catalog_gap(ROOT)
    assert not gap, (
        'компонентні CSS не підключені до каталогу: ' + ', '.join(gap)
        + '\nДодайте <link> у app/templates/admin/design_system.html і '
          'покажіть компоненти в потрібному табі. Якщо файл насправді '
          'посторінковий -- у нього має бути один споживач.'
    )
```

- [ ] **Step 2: Запустити — має впасти зі списком**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_design_system/test_catalog_links_components.py -v`
Expected: FAIL, у повідомленні ~36 імен файлів.

- [ ] **Step 3: Додати `<link>` на всі компонентні файли**

Список брати з виводу `python tools/ds/ds_audit.py` (розділ «КОМПОНЕНТНІ ФАЙЛИ ПОЗА КАТАЛОГОМ»), не з пам'яті. Кожен рядок — з `?v={{ assets_version }}`.

Порядок підключення має значення: спершу основа (`common` іде з `base.html`), далі спільні компоненти, посторінково-компонентні (`auth`, `registration`, `blog`, `legal`, `course-landing`) — після них. Над блоком поставити коментар, що порядок навмисний.

- [ ] **Step 4: Запустити — має пройти**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_design_system/ -v`
Expected: PASS.

- [ ] **Step 5: Написати на сторінці, чому каталог поки що не остаточна істина**

У таб «Правила» (`_tab_rules.html`) додати секцію звичайною розміткою каталогу (`ds-section`), текстом приблизно таким:

> **Межа цієї сторінки.** Тут підключено всі компонентні CSS одночасно. У 69 місцях один клас оголошений у двох файлах, і виграє той, що підключений останнім — тобто компонент на цій сторінці може виглядати не так, як на реальній сторінці сайту. Це не вада каталогу, а видима проєкція боргу: доки клас має двох власників, правка дизайн-системи до частини сторінок не доходить. Поточне число — у `python tools/ds/ds_audit.py`.

Без inline-стилів; якщо потрібен виділений вигляд — брати наявний компонент попередження з `admin.css`, а не писати новий.

У тому ж табі, у розділі «Не показується», дописати рядки про `fonts.css` і `material-symbols.css`: вони компонентні за межею (споживачів багато), але це інфраструктура шрифтів, показувати в каталозі нема чого. Розділ «Не показується» — саме те місце, де таке рішення лишається на очах у читача, а не ховається в код тесту.

- [ ] **Step 6: Знімок і коміт**

Run: `PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py capture --label after && PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py diff before after`
Expected: одна сторінка з розбіжністю — каталог.

```bash
git add app/templates/admin/design_system.html app/templates/design_system/_tab_rules.html tests/test_design_system/test_catalog_links_components.py
git commit -m "feat(design-system): каталог показує компоненти з тих самих файлів, що й сайт"
```

---

### Task 6: Перейменування 20 файлів

**Files:**
- Rename: 10 компонентних (`page-*` -> без префікса) і 10 посторінкових (без префікса -> `page-*`)
- Modify: ~40 шаблонів із посиланнями

**Interfaces:**
- Consumes: `ds_audit.naming_mismatch` (Task 1).

Перейменування нічого не лагодить — воно робить так, щоб назва файлу не брехала про його роль. Тому окремим комітом і **після** того, як сторожі й знімок уже працюють.

- [ ] **Step 1: Знімок ДО**

Run: `PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py capture --label before`

- [ ] **Step 2: Взяти актуальний список**

Run: `PYTHONIOENCODING=utf-8 python tools/ds/ds_audit.py`

Розділ «ІМ'Я СУПЕРЕЧИТЬ СУТІ» — це і є список. Очікується 20 рядків:

- втрачають префікс: `page-quiz`, `page-account`, `page-courses`, `page-clinics`, `page-trainers`, `page-online-course`, `page-online-courses`, `page-admin-integration`, `page-admin-notifications`, `page-admin-perf`;
- отримують префікс: `admin-backup`, `admin-cities`, `admin-error-logs`, `admin-participants`, `admin-regalia`, `admin-translations`, `admin-webhooks`, `blog-editor`, `materials-trainer`, `design-system`.

**Якщо список відрізняється від очікуваного — довіряти інструменту, а не плану:** між написанням плану і роботою хтось міг додати файл.

**`design-system.css` інструмент у цьому списку НЕ покаже — і це правильно.** Його єдиний споживач — сам каталог, а каталог із підрахунку споживачів виключений (інакше кожен показаний клас робив би свій файл компонентним сам собою). Тому в нього виходить нуль споживачів, і в `should_gain_prefix` він не потрапляє: там умова «рівно один». Перейменувати його все одно треба — це chrome каталогу, тобто посторінковий файл за суттю. Разом виходить 19 із інструмента плюс цей один.

- [ ] **Step 3: Перейменувати по одному файлу за раз**

Для кожного: `git mv app/static/css/<old>.css app/static/css/<new>.css`, далі замінити посилання в шаблонах:

```bash
grep -rln "css/<old>.css" app/templates/ | xargs sed -i "s|css/<old>\.css|css/<new>.css|g"
```

Перевірити, що не лишилось згадок ніде, включно з python і js:

```bash
grep -rn "<old>\.css" app/ tools/ tests/ docs/ | grep -v "\.pyc"
```

`design-system.css` згадується ще й у `tools/ds/ds_audit.py` (`CATALOG_GLOBS` не чіпає, але коментарі можуть) і в `tools/ds/README.md` — перевірити обидва.

- [ ] **Step 4: Запустити всі тести**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/ -q`
Expected: усе зелене. `test_css_markup_sync.py` фільтрує файли за префіксом `admin`/`page-admin` (рядок 114) — після перейменування `admin-webhooks.css` стає `page-admin-webhooks.css`, і фільтр його все одно ловить. **Перевірити це окремо**: якщо кількість перевірених файлів впала, фільтр треба поправити, а не радіти зеленому.

- [ ] **Step 5: Знімок — нуль розбіжностей**

Run: `PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py capture --label after && PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py diff before after`
Expected: **нуль**. Перейменування не змінює жодного байта розмітки, крім імен файлів у `<link>`… а вони в розмітці є. Тому очікується розбіжність на КОЖНІЙ сторінці, де змінилось посилання, і кожну треба звірити очима: змінився лише шлях у `href`, більше нічого.

- [ ] **Step 6: Оновити baseline і аудит**

Run: `PYTHONIOENCODING=utf-8 python tools/ds/ds_audit.py --write-baseline`

Імена файлів у baseline змінились, число дублікатів — ні (69). Інструмент відмовиться писати, якщо число зросло.

- [ ] **Step 7: Commit**

```bash
git add app/static/css/ app/templates/ tests/test_design_system/duplicate_classes_baseline.json
git commit -m "refactor(css): назва файлу більше не бреше про його роль"
```

---

### Task 7: Концепт у документації

**Files:**
- Modify: `C:\Users\aksqu\.claude\CLAUDE.md`
- Modify: `.claude/commands/ds-consolidate.md`
- Modify: `tools/ds/README.md`

- [ ] **Step 1: Записати концепт у CLAUDE.md**

У розділ `MAIN REQUIREMENTS`, після рядка про Custom CSS Design System, додати:

```markdown
### Дизайн-система -- джерело істини

Дизайн-система -- основа, з якої всі сторінки черпають стилі окремих
елементів. Кнопки, шрифти, поля вводу, форми, таблиці, нотифікації, рядки
завантаження, бейджі, порожні стани оголошуються в ній ОДИН раз; сторінка
їх лише перевикористовує.

`page-*.css` -- стилі, унікальні для однієї сторінки, і за суттю це layout:
сітка, ширини колонок, порядок і відступи блоків саме тут. Декору (колір,
шрифт, межа, тінь) у ньому бути не повинно.

Критерій, за яким це перевіряється: правка компонента в дизайн-системі
мусить впливати на ВСІ сторінки, де він вживається. Порушується це рівно
тоді, коли клас оголошений більш ніж в одному файлі.

Каталог: /admin/design-system. Числа: python tools/ds/ds_audit.py.
Сторожі: pytest tests/test_design_system/.
```

- [ ] **Step 2: Переписати `/ds-consolidate` під концепт**

Три зміни, кожна — заміна наявного тексту, не дописування:

1. У розділі «Контекст проєкту» замінити абзац «Що вже зроблено і чим це стережеться» на актуальний: каталог у адмінці, сторожів тепер чотири (покриття, розмітка↔CSS в обидва боки, підключення компонентних файлів, храповик дублікатів), публічний шар усе ще не покритий тестом покриття.
2. У Фазі 0 замінити опис сканів на запуск `python tools/ds/ds_audit.py` з таблицею «що означає кожне число» і поточними значеннями: дублікатів 69, декору в `page-*` 222 класи у 18 файлах, компонентних поза каталогом 0, розбіжностей імені й суті 0.
3. У Фазі 3 замість «заведи тести» — перелік наявних чотирьох із файлами і тим, що саме кожен ловить.

Плюс новий короткий розділ «Три артефакти» одразу після «Головного правила»:

```markdown
## Три артефакти

* `tools/ds/html_snapshot.py` -- доказ, що правка нічого не зламала;
* `tools/ds/ds_audit.py` -- числа концепту: де він порушений і наскільки;
* `tests/test_design_system/` -- інваріанти, що падають у CI.

Скіл -- процедура, яка ними керує. Він не міряє сам і не перевіряє сам.
```

- [ ] **Step 3: Перевірити, що документ не бреше**

Кожне число в тексті звірити з живим прогоном `ds_audit.py`, кожен шлях до файлу — відкрити. Документ, який називає неіснуючий файл, шкідливіший за його відсутність.

- [ ] **Step 4: Commit**

```bash
git add .claude/commands/ds-consolidate.md tools/ds/README.md
git commit -m "docs(design-system): концепт джерела істини і як він перевіряється"
```

CLAUDE.md лежить поза репозиторієм — він не комітиться.

---

## Перевірка Етапу 1 цілком

Після Задачі 7 усе разом:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/ -q
PYTHONIOENCODING=utf-8 python tools/ds/html_snapshot.py noise
PYTHONIOENCODING=utf-8 python tools/ds/ds_audit.py
```

Умови завершеності:
- усі тести зелені, зокрема чотири сторожі дизайн-системи;
- шум знімка — нуль;
- аудит: компонентних файлів поза каталогом **0**, розбіжностей імені й суті **0**, дублікатів **69** (baseline зафіксовано), декору в `page-*` — 222 (робота Етапу 3);
- `/admin/design-system` відкривається під адміном, п'ять табів перемикаються клавіатурою, `/design-system` веде на нього 302-м.

## Що Етап 1 свідомо НЕ робить

- не зводить 69 дублікатів (Етап 2);
- не чистить 222 елементні правила в `page-*` (Етап 3);
- не розширює `test_catalog_coverage.py` за межі `admin.css`;
- не виносить `tabs.css`/`tabs.js` із `base.html`, хоча вони їдуть на кожну публічну сторінку заради однієї адмінської — це зміна завантаження всіх сторінок, їй місце в перф-задачі;
- не змінює візуальну мову жодної сторінки, крім самого каталогу.
