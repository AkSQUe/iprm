"""Вітрина /design-system мусить бути повним каталогом базових елементів.

Кожен клас-БЛОК, оголошений в admin.css, має бути згаданий на вітрині:
компонент -- живою розміткою, утиліта -- рядком у таблиці утиліт, каркас
сторінки -- підписом у переліку.

Чому тест, а не домовленість: до нього вітрина показувала 36 класів із 217,
і саме тому в page-файлах заводились копії -- побачити наявний компонент
було важче, ніж написати свій. Список-виняток тут навмисно НЕ ведеться:
винятком є сама вітрина. Якщо клас справді не варто показувати, його треба
згадати в розділі «Не показується» з поясненням -- і тест це прийме, бо
клас у файлі є. Так рішення лишається в очах читача вітрини, а не
в python-списку, який розсинхронізується так само, як розсинхронізувалась
вітрина.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / 'app' / 'static' / 'css' / 'admin.css'
SHOWCASE_DIR = ROOT / 'app' / 'templates' / 'design_system'


def _showcase_text():
    """Каталог тепер -- п'ять партіалів під табами, а не один файл."""
    return '\n'.join(
        p.read_text(encoding='utf-8') for p in sorted(SHOWCASE_DIR.glob('_tab_*.html'))
    )


def _blocks():
    """Класи-блоки admin.css: без __елементів, --модифікаторів і станів."""
    css = re.sub(r'/\*.*?\*/', ' ', CSS.read_text(encoding='utf-8'), flags=re.S)
    out = set()
    for head in re.findall(r'([^{}]+)\{', css):
        if '@' in head:
            continue
        for cls in re.findall(r'\.([a-z][\w-]*)', head):
            if '__' in cls or '--' in cls or cls.startswith('is-'):
                continue
            out.add(cls)
    return out


@pytest.fixture(scope='module')
def showcase_words():
    text = _showcase_text()
    return set(re.findall(r'[\w-]+', text))


@pytest.mark.parametrize('cls', sorted(_blocks()))
def test_block_is_on_showcase(cls, showcase_words):
    assert cls in showcase_words, (
        f'клас .{cls} оголошений в admin.css, але на /design-system його немає.\n'
        f'Додайте його у відповідний app/templates/design_system/_tab_*.html: компонент -- '
        f'живою розміткою, утиліту -- рядком у таблиці утиліт. Якщо показувати '
        f'нема чого (каркас сторінки, шрифтовий клас) -- впишіть його в розділ '
        f'«Не показується» з поясненням, чому.'
    )


def test_showcase_has_no_stale_admin_classes(showcase_words):
    """Зворотний бік: вітрина не має показувати те, чого в CSS уже немає.

    Саме так на сторінках і жили класи без правил (.admin-badge малювався
    голим текстом, бо правила не було ніде) -- вітрина мовчки їх узаконювала.
    """
    blocks = _blocks()
    text = _showcase_text()
    used = set()
    for attr in re.findall(r'class="([^"]*)"', text):
        for token in attr.split():
            if token.startswith('admin-') and '{' not in token:
                used.add(re.sub(r'(__|--).*$', '', token))
    unknown = sorted(c for c in used - blocks if not c.startswith('admin-hero'))
    assert not unknown, (
        'вітрина показує класи, яких в admin.css немає: '
        + ', '.join(unknown)
    )


# --- крос-доменні компоненти -------------------------------------------
#
# Тест вище знає лише `admin.css`. Публічний шар каталог показує, але ніщо
# не змушує тримати його там повним -- і саме туди й дивиться цей блок.
#
# Чому не «всі класи всіх компонентних файлів»: їх 421, і 271 у каталозі
# немає. «Компонентний файл» не дорівнює «перевикористовуваний компонент»:
# `blog-card` живе у двох блогових шаблонах і жодній іншій сторінці не
# потрібен. Тест на 421 упав би першого ж дня з 271 порушенням, і його
# вимкнули б -- рівно те, проти чого цей проєкт працює.
#
# Міряємо вужче й чесніше: клас, який вживають ДВА РІЗНІ ДОМЕНИ (теки
# верхнього рівня в app/templates), -- справжній спільний компонент. Його
# неминуче шукатиме наступний, і не знайшовши в каталозі, напише свій.
#
# Храповик, а не вимога нуля: 31 такий клас уже поза каталогом. Показати їх
# усі -- окрема робота (жива розмітка на кожен), а тест не дає з'явитись
# 32-му. Прибрав із baseline -- отже показав у каталозі.
import json
import sys

sys.path.insert(0, str(ROOT / 'tools' / 'ds'))
import ds_audit  # noqa: E402

GAP_BASELINE = Path(__file__).parent / 'catalog_gap_baseline.json'


def test_no_new_cross_domain_component_outside_catalog(showcase_words):
    baseline = json.loads(GAP_BASELINE.read_text(encoding='utf-8'))
    current = ds_audit.cross_domain_components(ROOT)
    fresh = sorted(c for c in current if c not in showcase_words and c not in baseline)
    assert not fresh, (
        'спільні компоненти, яких немає в каталозі: '
        + ', '.join('.%s (%s)' % (c, ', '.join(current[c])) for c in fresh)
        + '\nКлас вживають кілька доменів -- отже це компонент, а не деталь '
          'однієї сторінки. Покажіть його в app/templates/design_system/'
          '_tab_*.html: не побачивши його там, наступний напише свій.'
    )


def test_catalog_gap_baseline_only_shrinks(showcase_words):
    """Показали компонент -- приберіть його з baseline."""
    baseline = json.loads(GAP_BASELINE.read_text(encoding='utf-8'))
    current = ds_audit.cross_domain_components(ROOT)
    still_missing = {c for c in current if c not in showcase_words}
    assert len(still_missing) <= len(baseline), (
        'компонентів поза каталогом стало більше: %d проти %d у baseline'
        % (len(still_missing), len(baseline))
    )
