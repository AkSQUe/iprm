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
SHOWCASE = ROOT / 'app' / 'templates' / 'design_system' / '_content.html'


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
    text = SHOWCASE.read_text(encoding='utf-8')
    return set(re.findall(r'[\w-]+', text))


@pytest.mark.parametrize('cls', sorted(_blocks()))
def test_block_is_on_showcase(cls, showcase_words):
    assert cls in showcase_words, (
        f'клас .{cls} оголошений в admin.css, але на /design-system його немає.\n'
        f'Додайте його у app/templates/design_system/_content.html: компонент -- '
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
    text = SHOWCASE.read_text(encoding='utf-8')
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
