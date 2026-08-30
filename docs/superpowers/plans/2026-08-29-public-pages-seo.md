# SEO публічних сторінок -- план впровадження

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрити прогалини у структурованих даних публічних сторінок,
звести хлібні крихти до одного оголошення і поставити pytest-сторожі, які
не дають SEO-боргу повернутись.

**Architecture:** Спершу пишуться сторожі, які фіксують ПОТОЧНУ поведінку
разом з іменованим списком відомого боргу. Далі зʼявляється спільний шар
(`abs_url` + макрос `breadcrumbs`), на який переводяться девʼять копій
`BreadcrumbList`; сторожі доводять, що вихід не змінився. Потім
закриваються прогалини покриття і додаються рейтинги з реальних відгуків.

**Tech Stack:** Flask 3, Jinja2, SQLAlchemy, pytest, schema.org JSON-LD.

**Spec:** `docs/superpowers/specs/2026-08-29-public-pages-seo-design.md`

## Global Constraints

* Кожен JSON-LD будується як Jinja-dict і віддається через `|tojson`.
  Літеральний JSON у шаблоні заборонений.
* Усі URL у структурованих даних абсолютні. Відносний шлях у `image`,
  `logo`, `item`, `url` -- дефект.
* Структуровані дані описують лише те, що реально є на сторінці. Розмітка
  з демо-заглушки заборонена без винятків.
* Компонент оголошується один раз (той самий критерій, що для CSS у
  `CLAUDE.md`).
* Без emoji. Без inline-коду. Коментарі українською.
* НЕ чіпати: `_hreflang_alternates()`, `localized_urls()`, `alt` на
  зображеннях, наявні `Course`/`CourseInstance`/`Offer`/`FAQPage`/
  `Person`/`BlogPosting`.
* Поза межами: клініки (адреси, `MedicalClinic`, адмін-CRUD) і будь-яка
  робота з ключовими словами.

---

### Task 1: Каркас тестів і структурні сторожі

**Files:**
- Create: `tests/test_seo/__init__.py`
- Create: `tests/test_seo/helpers.py`
- Create: `tests/test_seo/test_page_seo.py`

**Interfaces:**
- Consumes: фікстури `app` і `client` з `tests/conftest.py`.
- Produces: `tests/test_seo/helpers.py` з
  `public_endpoints(app) -> list[str]`,
  `fetch_public_pages(app, client) -> list[tuple[str, str, str]]`
  (кортежі `(endpoint, url, html)`), `jsonld_blocks(html) -> list[dict]`
  і константами `PRIVATE_BLUEPRINTS: set[str]`,
  `SERVICE_ENDPOINTS: set[str]`, `KNOWN_SEO_DEBT: dict[str, str]`,
  `TITLE_MIN`/`TITLE_MAX`/`DESC_MIN`/`DESC_MAX: int`,
  `LENGTH_EXCEPTIONS: dict[str, str]`.

Чому список боргу, а не пом'якшені межі: сторож має ловити НОВИЙ борг з
першого дня, а наявні дефекти закриває Задача 4. Запис у
`KNOWN_SEO_DEBT` -- це зобовʼязання, і тест падає не лише коли зʼявився
новий дефект, а й коли записаний дефект уже виправлено, але запис забули
прибрати.

- [ ] **Step 1: Створити каркас пакета і хелпери**

Створити `tests/test_seo/__init__.py` порожнім файлом.

Створити `tests/test_seo/helpers.py`:

```python
"""Спільні хелпери SEO-сторожів: перелік публічних сторінок і список
відомого боргу."""
import json
import re

# Розділи, закриті від індексації (мають X-Robots-Tag у своїх __init__.py).
PRIVATE_BLUEPRINTS = {'admin', 'auth', 'payments', 'quiz', 'registration'}

# Службові ендпоінти: віддають не HTML, тож HTML-твердження до них не
# застосовні.
SERVICE_ENDPOINTS = {'static', 'main.robots', 'main.sitemap', 'media.serve'}

# Відомий SEO-борг: ендпоінт -> причина. Кожен запис прибирає Задача 4.
# Тест падає і тоді, коли записаний тут ендпоінт уже проходить перевірку:
# виправив -- прибери запис.
KNOWN_SEO_DEBT = {
    'main.labs': 'title дослівно дублює головну; власний дає Задача 4',
}

# Цільові межі довжин зі специфікації.
TITLE_MIN, TITLE_MAX = 30, 60
DESC_MIN, DESC_MAX = 120, 160

# Сторінки, чию довжину не виправити без рішення про контент: ендпоінт ->
# причина. Межі НЕ пом'якшуються -- виняток завжди іменований.
LENGTH_EXCEPTIONS = {}


def public_endpoints(app):
    """Ендпоінти публічних HTML-сторінок без обовʼязкових параметрів.

    Динамічні сторінки (курс, тренер, стаття) сюди не потрапляють -- вони
    потребують рядків у БД і перевіряються окремими тестами з фікстурами.
    """
    endpoints = set()
    for rule in app.url_map.iter_rules():
        if 'GET' not in rule.methods:
            continue
        if rule.endpoint in SERVICE_ENDPOINTS:
            continue
        if rule.endpoint.split('.')[0] in PRIVATE_BLUEPRINTS:
            continue
        # lang_code має дефолт, решта параметрів робить сторінку динамічною.
        if set(rule.arguments) - {'lang_code'}:
            continue
        endpoints.add(rule.endpoint)
    return sorted(endpoints)


def fetch_public_pages(app, client):
    """(endpoint, url, html) для кожної публічної сторінки, що віддала 200."""
    from flask import url_for

    with app.test_request_context():
        urls = {ep: url_for(ep) for ep in public_endpoints(app)}

    pages = []
    for endpoint, url in urls.items():
        resp = client.get(url)
        if resp.status_code != 200:
            continue
        pages.append((endpoint, url, resp.data.decode('utf-8')))
    return pages


def jsonld_blocks(html):
    """Розпарсені JSON-LD блоки сторінки. Кидає ValueError на невалідному."""
    raw = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        html, re.DOTALL,
    )
    return [json.loads(chunk) for chunk in raw]
```

- [ ] **Step 2: Написати структурні сторожі**

Створити `tests/test_seo/test_page_seo.py`:

```python
"""Сторожі публічних сторінок: заголовок, canonical, опис, валідність
структурованих даних."""
import re

from tests.test_seo.helpers import (
    DESC_MAX, DESC_MIN, KNOWN_SEO_DEBT, LENGTH_EXCEPTIONS,
    TITLE_MAX, TITLE_MIN, fetch_public_pages, jsonld_blocks,
)


class TestPageStructure:
    def test_exactly_one_h1(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            count = len(re.findall(r'<h1[\s>]', html))
            if count != 1:
                bad.append(f'{endpoint} ({url}): {count} <h1>')
        assert not bad, 'Сторінки не з одним <h1>:\n' + '\n'.join(bad)

    def test_canonical_absolute_and_clean(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            found = re.search(r'<link rel="canonical" href="([^"]*)"', html)
            if not found:
                bad.append(f'{endpoint}: canonical відсутній')
                continue
            href = found.group(1)
            if not href.startswith('http'):
                bad.append(f'{endpoint}: canonical не абсолютний -- {href}')
            if '?' in href:
                bad.append(f'{endpoint}: canonical із query -- {href}')
        assert not bad, 'Проблеми canonical:\n' + '\n'.join(bad)

    def test_meta_description_present(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            found = re.search(
                r'<meta name="description" content="([^"]*)"', html,
            )
            if not found or not found.group(1).strip():
                bad.append(f'{endpoint}: опис порожній або відсутній')
        assert not bad, 'Проблеми meta description:\n' + '\n'.join(bad)

    def test_jsonld_parses(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            try:
                blocks = jsonld_blocks(html)
            except ValueError as exc:
                bad.append(f'{endpoint}: невалідний JSON-LD -- {exc}')
                continue
            for block in blocks:
                if '@context' not in block:
                    bad.append(f'{endpoint}: блок без @context')
                # @graph -- валідна альтернатива @type на верхньому рівні;
                # так побудована схема головної.
                elif '@type' not in block and '@graph' not in block:
                    bad.append(f'{endpoint}: блок без @type і без @graph')
        assert not bad, 'Проблеми JSON-LD:\n' + '\n'.join(bad)


class TestTitleUniqueness:
    def _titles(self, app, client):
        titles = {}
        for endpoint, url, html in fetch_public_pages(app, client):
            found = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
            assert found, f'{endpoint}: <title> відсутній'
            titles[endpoint] = found.group(1).strip()
        return titles

    def test_titles_unique_except_known_debt(self, app, client):
        titles = self._titles(app, client)
        by_title = {}
        for endpoint, title in titles.items():
            by_title.setdefault(title, []).append(endpoint)

        # Дубль дозволений, лише поки хоча б один його ендпоінт значиться
        # у списку боргу.
        unexpected = {
            title: eps for title, eps in by_title.items()
            if len(eps) > 1 and not any(ep in KNOWN_SEO_DEBT for ep in eps)
        }
        assert not unexpected, f'Неврахований дубль title: {unexpected}'

    def test_known_debt_entries_are_still_real(self, app, client):
        """Виправив борг -- прибери запис. Інакше список бреше."""
        titles = self._titles(app, client)
        stale = []
        for endpoint in KNOWN_SEO_DEBT:
            if endpoint not in titles:
                continue
            twins = [
                other for other, title in titles.items()
                if title == titles[endpoint] and other != endpoint
            ]
            if not twins:
                stale.append(endpoint)
        assert not stale, f'KNOWN_SEO_DEBT застарів, прибери записи: {stale}'


class TestLengths:
    def test_title_and_description_within_targets(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            if endpoint in LENGTH_EXCEPTIONS:
                continue
            title = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
            desc = re.search(
                r'<meta name="description" content="([^"]*)"', html,
            )
            if title:
                length = len(title.group(1).strip())
                if not TITLE_MIN <= length <= TITLE_MAX:
                    bad.append(f'{endpoint}: title {length} симв.')
            if desc:
                length = len(desc.group(1).strip())
                if not DESC_MIN <= length <= DESC_MAX:
                    bad.append(f'{endpoint}: description {length} симв.')
        report = '; '.join(bad)
        assert not bad, (
            f'Поза межами title {TITLE_MIN}-{TITLE_MAX}, '
            f'description {DESC_MIN}-{DESC_MAX}: {report}'
        )
```

- [ ] **Step 3: Запустити сторожі**

Run: `python -m pytest tests/test_seo/ -v`
Expected: PASS. Дубль title на `main.labs` покритий записом у
`KNOWN_SEO_DEBT`.

`TestLengths` майже напевно впаде -- довжини ніхто не міряв. Це очікувано.
Для КОЖНОЇ сторінки зі списку падіння: занести ендпоінт у
`LENGTH_EXCEPTIONS` з причиною і фактичною довжиною, після чого тест
зеленіє. Межі `TITLE_MIN`/`DESC_MIN`/... НЕ змінювати -- виняток мусить
бути іменованим, а не розчиненим у послабленій межі. Повний список
винятків навести у звіті: Задача 4 перепише ті рядки, які можна
переписати без рішення про контент.

Якщо впав інший тест -- це реальний дефект, якого не було в аудиті.
`KNOWN_SEO_DEBT` його НЕ покриває: цей словник читають лише тести
унікальності title. НЕ пом'якшувати твердження і не розширювати словник
на чужі тести. Натомість: описати дефект у звіті окремим пунктом і
залишити тест червоним, якщо правка виходить за межі Задачі 1. Контролер
плану вирішить, чи закривати його тут, чи Задачею 4.

- [ ] **Step 4: Перевірити, що решта сюїти ціла**

Run: `python -m pytest tests/ -q`
Expected: без нових падінь.

---

### Task 2: Сторожі URL, hreflang і noindex

**Files:**
- Modify: `tests/test_seo/helpers.py`
- Create: `tests/test_seo/test_urls_and_locales.py`

**Interfaces:**
- Consumes: `fetch_public_pages`, `jsonld_blocks` з Задачі 1.
- Produces: у `helpers.py` -- константа `URL_KEYS: tuple[str, ...]` і
  генератор `iter_url_values(node)`, що рекурсивно віддає пари
  `(ключ, значення)` для URL-полів JSON-LD.

- [ ] **Step 1: Додати обхід URL-полів**

Дописати в кінець `tests/test_seo/helpers.py`:

```python
# Поля JSON-LD, у яких Google очікує абсолютний URL.
URL_KEYS = ('image', 'logo', 'item', 'url')


def iter_url_values(node):
    """Пари (ключ, значення) для URL-полів усередині JSON-LD, рекурсивно."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in URL_KEYS:
                if isinstance(value, str):
                    yield key, value
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            yield key, item
            yield from iter_url_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_url_values(item)
```

- [ ] **Step 2: Написати тести URL, hreflang і noindex**

Створити `tests/test_seo/test_urls_and_locales.py`:

```python
"""Сторожі абсолютності URL у структурованих даних, набору hreflang і
закритості приватних розділів."""
import re

from app.i18n import LANGUAGES
from tests.test_seo.helpers import (
    fetch_public_pages, iter_url_values, jsonld_blocks,
)


class TestSchemaUrls:
    def test_schema_urls_absolute(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            for block in jsonld_blocks(html):
                for key, value in iter_url_values(block):
                    if not value.startswith('http'):
                        bad.append(f'{endpoint}: {key} = {value}')
        assert not bad, (
            'Відносні URL у структурованих даних:\n' + '\n'.join(bad)
        )


class TestHreflang:
    def test_localized_pages_list_all_languages(self, app, client):
        expected = set(LANGUAGES) | {'x-default'}
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            langs = set(re.findall(
                r'<link rel="alternate" hreflang="([^"]+)"', html,
            ))
            if not langs:
                # Нелокалізований ендпоінт (юридичні сторінки) -- штатно.
                continue
            if langs != expected:
                bad.append(f'{endpoint}: {sorted(langs)}')
        assert not bad, (
            f'Набір hreflang не дорівнює {sorted(expected)}:\n'
            + '\n'.join(bad)
        )

    def test_hreflang_urls_absolute(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            for href in re.findall(
                r'<link rel="alternate" hreflang="[^"]+" href="([^"]+)"', html,
            ):
                if not href.startswith('http'):
                    bad.append(f'{endpoint}: {href}')
        assert not bad, 'Відносні hreflang:\n' + '\n'.join(bad)


class TestPrivatePagesClosed:
    def test_private_blueprints_send_noindex_header(self, client):
        # X-Robots-Tag ставиться в after_request незалежно від коду
        # відповіді, тож редірект на логін теж має його нести.
        for path in ('/auth/login', '/registration/', '/quiz/'):
            resp = client.get(path, follow_redirects=False)
            header = resp.headers.get('X-Robots-Tag', '')
            assert 'noindex' in header, f'{path}: X-Robots-Tag = {header!r}'
```

- [ ] **Step 3: Запустити нові сторожі**

Run: `python -m pytest tests/test_seo/test_urls_and_locales.py -v`
Expected: `TestHreflang` і `TestPrivatePagesClosed` -- PASS.

`TestSchemaUrls` на статичних сторінках має пройти: відносні URL живуть
у схемі курсу, а курсові сторінки динамічні й у цей перелік не входять.
Якщо він усе-таки впав -- це той самий дефект `card_src`, який закриває
Задача 4. Тоді позначити КЛАС маркером

```python
@pytest.mark.xfail(reason='дефект card_src; знімає Задача 4', strict=True)
```

(і додати `import pytest`), назвати це у звіті. `strict=True`
обовʼязковий: після виправлення тест почне падати як "неочікувано
пройшов" і змусить зняти маркер.

- [ ] **Step 4: Перевірити повну сюїту**

Run: `python -m pytest tests/ -q`
Expected: без нових падінь.

---

### Task 3: Спільний шар структурованих даних

**Files:**
- Modify: `app/__init__.py` (поряд з рештою `app.jinja_env.globals`, близько рядка 249)
- Create: `app/templates/partials/schema/_breadcrumbs.html`
- Modify: `app/templates/clinics/detail.html`
- Modify: `app/templates/clinics/list.html`
- Modify: `app/templates/courses/detail.html`
- Modify: `app/templates/courses/list.html`
- Modify: `app/templates/online/detail.html`
- Modify: `app/templates/online/list.html`
- Modify: `app/templates/trainers/detail.html`
- Modify: `app/templates/trainers/list.html`
- Modify: `app/templates/main/bpr_documents.html`
- Create: `tests/test_seo/test_breadcrumbs.py`

**Interfaces:**
- Consumes: сторожі Задач 1-2 (мають лишитись зеленими).
- Produces:
  * Jinja-глобал `abs_url(path) -> str | None`. `None` на порожньому
    вході; шлях, що вже починається з `http://`/`https://`, повертається
    без змін; решта склеюється з `request.url_root`.
  * Макрос `breadcrumbs(items)` у
    `app/templates/partials/schema/_breadcrumbs.html`. `items` -- список
    кортежів `(name, url)`; порожній `url` означає поточну сторінку і не
    дає ключа `item`. Кореневий елемент "ІПРМ" макрос додає сам. Віддає
    ГОТОВИЙ тег `<script type="application/ld+json">`.

- [ ] **Step 1: Написати падаючі тести**

Створити `tests/test_seo/test_breadcrumbs.py`:

```python
"""Спільний шар: abs_url і макрос хлібних крихт."""
from tests.test_seo.helpers import jsonld_blocks


class TestAbsUrl:
    def test_none_for_empty(self, app):
        abs_url = app.jinja_env.globals['abs_url']
        with app.test_request_context():
            assert abs_url(None) is None
            assert abs_url('') is None

    def test_absolutizes_relative_path(self, app):
        abs_url = app.jinja_env.globals['abs_url']
        with app.test_request_context('/', base_url='https://iprm.space'):
            assert abs_url('/media/a/b.webp') == 'https://iprm.space/media/a/b.webp'

    def test_leaves_absolute_untouched(self, app):
        abs_url = app.jinja_env.globals['abs_url']
        with app.test_request_context('/', base_url='https://iprm.space'):
            src = 'https://cdn.example/x.png'
            assert abs_url(src) == src


def _breadcrumb(html):
    crumbs = [
        b for b in jsonld_blocks(html) if b.get('@type') == 'BreadcrumbList'
    ]
    assert len(crumbs) == 1, f'Очікували рівно одну BreadcrumbList, є {len(crumbs)}'
    return crumbs[0]


class TestBreadcrumbsMacro:
    def test_list_page_breadcrumb_shape(self, client):
        resp = client.get('/trainers/')
        assert resp.status_code == 200
        items = _breadcrumb(resp.data.decode('utf-8'))['itemListElement']
        assert [i['position'] for i in items] == [1, 2]
        assert items[0]['item'].startswith('http')
        # Поточна сторінка не має "item" за специфікацією schema.org.
        assert 'item' not in items[1]

    def test_breadcrumb_names_follow_locale(self, client):
        """Раніше назви крихт були захардкоджені українською і не
        перекладались. Макрос бере їх з переданих рядків."""
        uk = _breadcrumb(client.get('/trainers/').data.decode('utf-8'))
        en = _breadcrumb(client.get('/en/trainers/').data.decode('utf-8'))
        assert uk['itemListElement'][1]['name'] != en['itemListElement'][1]['name']
```

- [ ] **Step 2: Запустити -- має впасти**

Run: `python -m pytest tests/test_seo/test_breadcrumbs.py -v`
Expected: FAIL -- `abs_url` ще не зареєстрований (`KeyError: 'abs_url'`),
а назви крихт захардкоджені й однакові для uk та en.

- [ ] **Step 3: Зареєструвати глобал abs_url**

У `app/__init__.py`, після реєстрації `app.jinja_env.globals['icon_codepoints']`
(близько рядка 253), додати:

```python
    # Абсолютний URL для структурованих даних: Google не приймає у JSON-LD
    # відносний шлях, а MediaFile.url віддає саме такий (/media/...).
    # None на порожньому вході, щоб виклик не треба було обгортати в {% if %}.
    def _abs_url(path):
        if not path:
            return None
        if path.startswith(('http://', 'https://')):
            return path
        return request.url_root.rstrip('/') + '/' + path.lstrip('/')

    app.jinja_env.globals['abs_url'] = _abs_url
```

Переконатись, що `request` імпортовано з `flask` на початку файлу; якщо
ні -- додати до наявного імпорту.

- [ ] **Step 4: Створити макрос**

Створити `app/templates/partials/schema/_breadcrumbs.html`:

```jinja
{# BreadcrumbList -- ОДНЕ оголошення на весь проєкт.

   items: список (name, url). Кореневий "ІПРМ" макрос додає сам, тож
   сторінка передає лише свій хвіст. Порожній url означає поточну
   сторінку: за schema.org в останнього елемента "item" не буває.

   Назви приходять рядками від сторінки, а не хардкодяться тут -- інакше
   на ru/en крихти лишаються українськими, як було до цього макроса.

   Імпортувати ЛИШЕ як `... import breadcrumbs with context`:
   site_settings приходить з контекст-процесора, а імпортований без
   контексту макрос його не бачить і впаде на UndefinedError. #}
{% macro breadcrumbs(items) -%}
{%- set _elements = [{
  '@type': 'ListItem', 'position': 1,
  'name': site_settings.t('company_name') or _('ІПРМ'),
  'item': url_for('main.index', _external=True),
}] -%}
{%- for name, url in items -%}
  {%- set _el = {'@type': 'ListItem', 'position': loop.index + 1, 'name': name} -%}
  {%- if url %}{% set _discard = _el.update({'item': url}) %}{% endif -%}
  {%- set _discard = _elements.append(_el) -%}
{%- endfor -%}
<script type="application/ld+json">{{ {
  '@context': 'https://schema.org',
  '@type': 'BreadcrumbList',
  'itemListElement': _elements,
} | tojson }}</script>
{%- endmacro %}
```

- [ ] **Step 5: Перевести девʼять шаблонів на макрос**

У КОЖНОМУ файлі додати імпорт одразу після `{% extends %}`:

```jinja
{% from 'partials/schema/_breadcrumbs.html' import breadcrumbs with context %}
```

і замінити літеральний `<script type="application/ld+json">` з
`BreadcrumbList` на виклик макроса. Решту вмісту блоку `jsonld`
(включно з `{{ super() }}`, `Course`-схемою та include FAQ) НЕ чіпати.

Пастка в `online/detail.html`: там уже є `{% set breadcrumbs = {...} %}` --
змінна з тим самим імʼям, що й макрос, і вона його затінить. Прибрати
і цей `set`, і рядок `<script ...>{{ breadcrumbs | tojson }}</script>`
цілком, а не лише другий із них.

Пастка з коренем крихт: `online/detail.html` і `courses/detail.html`
беруть назву кореня з `site_settings.t('company_name')`, а решта сімох
хардкодить "ІПРМ". Макрос уніфікує це на `company_name` з фолбеком, тож
на семи сторінках назва кореня може змінитись -- це і є мета, а не
регресія.

```jinja
{# trainers/list.html #}
{{ breadcrumbs([(_('Тренери'), '')]) }}

{# trainers/detail.html #}
{{ breadcrumbs([
  (_('Тренери'), url_for('trainers.trainer_list', _external=True)),
  (trainer.t('full_name'), ''),
]) }}

{# clinics/list.html #}
{{ breadcrumbs([(_('Клініки'), '')]) }}

{# clinics/detail.html #}
{{ breadcrumbs([
  (_('Клініки'), url_for('clinics.clinic_list', _external=True)),
  (clinic.t('name'), ''),
]) }}

{# courses/list.html #}
{{ breadcrumbs([(_('Курси'), '')]) }}

{# courses/detail.html #}
{{ breadcrumbs([
  (_('Курси'), url_for('courses.course_list', _external=True)),
  (course.t('title'), ''),
]) }}

{# online/list.html #}
{{ breadcrumbs([(_('Онлайн-курси'), '')]) }}

{# online/detail.html #}
{{ breadcrumbs([
  (_('Онлайн-курси'), url_for('online.course_list', _external=True)),
  (course.effective_title, ''),
]) }}

{# main/bpr_documents.html #}
{{ breadcrumbs([(_('Документи БПР'), '')]) }}
```

- [ ] **Step 6: Запустити тести шару**

Run: `python -m pytest tests/test_seo/test_breadcrumbs.py -v`
Expected: PASS.

- [ ] **Step 7: Довести вихід-нейтральність міграції**

Run: `python -m pytest tests/test_seo/ tests/test_routes/ tests/test_i18n/ -q`
Expected: без нових падінь. Саме сторожі Задач 1-2 доводять, що
переписані девʼять шаблонів віддають те саме.

- [ ] **Step 8: Перевірити, що літеральних крихт не лишилось**

Run: `grep -rn "BreadcrumbList" app/templates/ | grep -v "partials/schema/"`
Expected: порожній вивід.

---

### Task 4: Прогалини покриття

**Files:**
- Modify: `app/templates/blog/list.html`
- Modify: `app/templates/main/index.html`
- Modify: `app/templates/main/offer.html`
- Modify: `app/templates/main/privacy.html`
- Modify: `app/templates/main/refund.html`
- Modify: `app/templates/main/disclaimer.html`
- Modify: `app/templates/main/cookies.html`
- Modify: `app/templates/courses/detail.html`
- Modify: `app/templates/online/detail.html`
- Modify: `tests/test_seo/helpers.py`
- Modify: `tests/test_seo/test_urls_and_locales.py` (лише якщо Задача 2 поставила xfail)

**Interfaces:**
- Consumes: макрос `breadcrumbs` і глобал `abs_url` із Задачі 3.
- Produces: нічого для наступних задач.

Це пачка дрібних однорідних правок. Виконувати як одну задачу.

- [ ] **Step 1: Додати крихти на сторінки без них**

У кожен файл -- імпорт після `{% extends %}`:

```jinja
{% from 'partials/schema/_breadcrumbs.html' import breadcrumbs with context %}
```

Блоку `jsonld` у цих файлах немає -- створити його з `super()`, щоб не
загубити схему організації з `base.html`:

```jinja
{# blog/list.html -- плюс тип Blog для розділу #}
{% block jsonld %}
{{ super() }}
<script type="application/ld+json">{{ {
  '@context': 'https://schema.org',
  '@type': 'Blog',
  'name': _('Блог ІПРМ'),
  'url': url_for('blog.index', _external=True),
} | tojson }}</script>
{{ breadcrumbs([(_('Блог'), '')]) }}
{% endblock %}

{# main/index.html (лабораторії) #}
{% block jsonld %}
{{ super() }}
{{ breadcrumbs([(_('Лабораторії'), '')]) }}
{% endblock %}

{# main/offer.html #}
{% block jsonld %}
{{ super() }}
{{ breadcrumbs([(_('Публічна оферта'), '')]) }}
{% endblock %}

{# main/privacy.html #}
{% block jsonld %}
{{ super() }}
{{ breadcrumbs([(_('Політика конфіденційності'), '')]) }}
{% endblock %}

{# main/refund.html #}
{% block jsonld %}
{{ super() }}
{{ breadcrumbs([(_('Умови повернення'), '')]) }}
{% endblock %}

{# main/disclaimer.html #}
{% block jsonld %}
{{ super() }}
{{ breadcrumbs([(_('Відмова від відповідальності'), '')]) }}
{% endblock %}

{# main/cookies.html #}
{% block jsonld %}
{{ super() }}
{{ breadcrumbs([(_('Політика cookie'), '')]) }}
{% endblock %}
```

- [ ] **Step 2: Дати сторінці лабораторій власний title**

У `app/templates/main/index.html` замінити рядок 3 на:

```jinja
{% block title %}{{ _('Лабораторії біологічного віку | ІПРМ') }}{% endblock %}
```

Головна (`main/home.html`) свій title НЕ змінює -- дубль знімається саме
з боку лабораторій.

- [ ] **Step 3: Спорожнити KNOWN_SEO_DEBT**

У `tests/test_seo/helpers.py`:

```python
# Відомий SEO-борг: ендпоінт -> причина. Порожньо -- борг закритий.
# Додавати запис можна лише разом із задачею, що його прибирає.
KNOWN_SEO_DEBT = {}
```

- [ ] **Step 3b: Розібрати LENGTH_EXCEPTIONS**

Задача 1 занесла у `LENGTH_EXCEPTIONS` сторінки, чий title або
description вийшов за межі. Пройти список:

* якщо рядок можна переписати в межі, лишивши сенс (скоротити title,
  дописати description) -- переписати у відповідному шаблоні і ПРИБРАТИ
  запис зі словника;
* якщо ні (назва розділу коротша за 30 символів за своєю природою) --
  лишити запис, але дописати в причину, ЧОМУ переписати не можна.

Порожньої причини у словнику лишитись не повинно. Список того, що
лишилось, навести у звіті.

- [ ] **Step 4: Абсолютизувати URL зображень у схемі курсу**

У `app/templates/courses/detail.html` замінити накопичення `_images`:

```jinja
{% set _images = [] %}
{% if course.card_src %}{% set _discard = _images.append(abs_url(course.card_src)) %}{% endif %}
{% for media in gallery or [] %}{% set _discard = _images.append(abs_url(media.url)) %}{% endfor %}
```

і водночас перекласти дані інструктора:

```jinja
{% if course.trainer %}{% set _discard = course_schema.update({'instructor': {
  '@type': 'Person',
  'name': course.trainer.t('full_name'),
  'jobTitle': course.trainer.t('role') or ''
}}) %}{% endif %}
```

У `app/templates/online/detail.html` замінити єдине місце, де зображення
потрапляє у схему:

```jinja
{% if course.card_src or course.hero_src %}
{% set _discard = course_schema.update({'image': abs_url(course.card_src or course.hero_src)}) %}
{% endif %}
```

- [ ] **Step 5: Зняти xfail, якщо Задача 2 його ставила**

Якщо `TestSchemaUrls` має маркер `xfail(strict=True)` -- прибрати його
разом із зайвим `import pytest`, якщо той більше не потрібен.

- [ ] **Step 6: Запустити сторожі**

Run: `python -m pytest tests/test_seo/ -v`
Expected: PASS, включно з `test_titles_unique_except_known_debt`,
`test_known_debt_entries_are_still_real` і `TestSchemaUrls`.

- [ ] **Step 7: Повна сюїта**

Run: `python -m pytest tests/ -q`
Expected: без нових падінь.

---

### Task 5: Рейтинги з реальних відгуків

**Files:**
- Create: `app/templates/partials/schema/_aggregate_rating.html`
- Modify: `app/courses/routes.py`
- Modify: `app/online/routes.py`
- Modify: `app/templates/courses/detail.html`
- Modify: `app/templates/online/detail.html`
- Create: `tests/test_seo/test_aggregate_rating.py`

**Interfaces:**
- Consumes: макрос-шар із Задачі 3.
- Produces: макрос `apply_rating(schema, reviews)` у
  `app/templates/partials/schema/_aggregate_rating.html`. Мутує
  переданий dict-схему, додаючи ключі `aggregateRating` і `review`.
  На порожньому списку не додає НІЧОГО і не друкує нічого.
  В'ю курсу та онлайн-курсу передають у шаблон `course_reviews`.

Правило, яке цей код втілює без винятків: якщо привʼязаних
опублікованих відгуків немає -- у структуровані дані не йде нічого.
Демо-цитати з `main/home.html` не є рядками БД і джерелом бути не можуть.

- [ ] **Step 1: Написати падаючі тести**

Створити `tests/test_seo/test_aggregate_rating.py`:

```python
"""AggregateRating будується лише з реальних опублікованих відгуків."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.review import Review
from tests.test_seo.helpers import jsonld_blocks


@pytest.fixture
def course_without_reviews(app):
    course = Course(
        title='Курс без відгуків', slug=f'ar-none-{uuid4().hex[:6]}',
        is_active=True,
    )
    db.session.add(course)
    db.session.flush()
    return course


@pytest.fixture
def course_with_reviews(app):
    course = Course(
        title='Курс з відгуками', slug=f'ar-some-{uuid4().hex[:6]}',
        is_active=True,
    )
    db.session.add(course)
    db.session.flush()
    db.session.add_all([
        Review(author_name='А', text='Добре', rating=5,
               is_published=True, course_id=course.id),
        Review(author_name='Б', text='Норм', rating=3,
               is_published=True, course_id=course.id),
        # Неопублікований у розрахунок НЕ входить.
        Review(author_name='В', text='Чернетка', rating=1,
               is_published=False, course_id=course.id),
    ])
    db.session.flush()
    return course


def _course_schema(html):
    for block in jsonld_blocks(html):
        if block.get('@type') == 'Course':
            return block
    raise AssertionError('Course-схеми на сторінці немає')


class TestAggregateRating:
    def test_absent_without_reviews(self, client, course_without_reviews):
        resp = client.get(f'/courses/{course_without_reviews.slug}')
        assert resp.status_code == 200
        schema = _course_schema(resp.data.decode('utf-8'))
        assert 'aggregateRating' not in schema
        assert 'review' not in schema

    def test_built_from_published_reviews_only(self, client, course_with_reviews):
        resp = client.get(f'/courses/{course_with_reviews.slug}')
        assert resp.status_code == 200
        schema = _course_schema(resp.data.decode('utf-8'))
        rating = schema['aggregateRating']
        assert rating['@type'] == 'AggregateRating'
        # Середнє (5 + 3) / 2 = 4; чернетка з rating=1 не враховується.
        assert float(rating['ratingValue']) == 4.0
        assert int(rating['reviewCount']) == 2
        assert len(schema['review']) == 2
```

- [ ] **Step 2: Запустити -- має впасти**

Run: `python -m pytest tests/test_seo/test_aggregate_rating.py -v`
Expected: FAIL -- `KeyError: 'aggregateRating'` у другому тесті.

Якщо URL сторінки курсу відрізняється від `/courses/<slug>` -- узяти
фактичний з `app/courses/routes.py` і виправити тест, а не маршрут.

- [ ] **Step 3: Передати відгуки курсу в шаблон**

У `app/courses/routes.py`, у в'ю сторінки курсу, перед `render_template`
додати:

```python
    course_reviews = Review.alive().filter_by(
        is_published=True, course_id=course.id,
    ).order_by(Review.sort_order, Review.created_at.desc()).all()
```

і передати `course_reviews=course_reviews` у `render_template`.
Імпорт угорі файлу: `from app.models.review import Review`.

У `app/online/routes.py` -- те саме, але `online_course_id=course.id`.

Якщо в'ю ВЖЕ дістає відгуки під іншим імʼям -- використати наявний
список і НЕ додавати другий запит до БД.

- [ ] **Step 4: Створити макрос рейтингу**

Створити `app/templates/partials/schema/_aggregate_rating.html`:

```jinja
{# AggregateRating + вузли Review для схеми курсу.

   Джерело -- ЛИШЕ опубліковані рядки Review, привʼязані до цього курсу.
   Порожній список означає, що макрос не додає нічого: розмітки не буде
   взагалі. Демо-цитати з головної сюди потрапити не можуть -- вони не є
   рядками БД.

   Макрос МУТУЄ переданий schema, а не повертає JSON: схема курсу
   збирається dict-ом вище по шаблону, і вливати фрагмент рядком
   означало б парсити його назад. #}
{% macro apply_rating(schema, reviews) -%}
{%- if reviews -%}
  {%- set _values = reviews | map(attribute='rating') | list -%}
  {%- set _nodes = [] -%}
  {%- for review in reviews -%}
    {%- set _discard = _nodes.append({
      '@type': 'Review',
      'author': {'@type': 'Person', 'name': review.t('author_name')},
      'reviewRating': {
        '@type': 'Rating', 'ratingValue': review.rating,
        'bestRating': 5, 'worstRating': 1,
      },
      'reviewBody': review.t('text'),
    }) -%}
  {%- endfor -%}
  {%- set _discard = schema.update({
    'aggregateRating': {
      '@type': 'AggregateRating',
      'ratingValue': ((_values | sum) / (_values | length)) | round(1),
      'reviewCount': _values | length,
      'bestRating': 5,
      'worstRating': 1,
    },
    'review': _nodes,
  }) -%}
{%- endif -%}
{%- endmacro %}
```

- [ ] **Step 5: Застосувати макрос на сторінці курсу**

У `app/templates/courses/detail.html` додати імпорт після `{% extends %}`:

```jinja
{% from 'partials/schema/_aggregate_rating.html' import apply_rating with context %}
```

і викликати ПІСЛЯ повного формування `course_schema`, але ПЕРЕД
`{% block jsonld %}`:

```jinja
{{ apply_rating(course_schema, course_reviews) }}
```

- [ ] **Step 6: Те саме для онлайн-курсу**

У `app/templates/online/detail.html` додати той самий імпорт і виклик
`apply_rating` для схеми онлайн-курсу з тим самим `course_reviews`.

- [ ] **Step 7: Запустити тести рейтингу**

Run: `python -m pytest tests/test_seo/test_aggregate_rating.py -v`
Expected: PASS.

- [ ] **Step 8: Повна сюїта**

Run: `python -m pytest tests/ -q`
Expected: без нових падінь.

---

## Критерій готовності плану

* `python -m pytest tests/test_seo/` -- зелений.
* `grep -rn "BreadcrumbList" app/templates/ | grep -v partials/schema/` -- порожньо.
* `KNOWN_SEO_DEBT` порожній.
* Повна сюїта без нових падінь.
