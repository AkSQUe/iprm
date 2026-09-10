"""Ключ ?v= мусить мінятись від БУДЬ-ЯКОГО статичного файлу, який ним версіюють.

Регресія: get_assets_version() хешувала лише static/css/*.css і static/js/*.js,
а шрифт іконок (static/fonts/material-symbols-rounded.woff2) підключений тим
самим ?v={{ assets_version }} у partials/_icon_font.html. Перегенерація субсету
без правки css/js лишала ключ незмінним, а nginx віддає /static/ з
`expires 30d; Cache-Control: public, immutable` -- браузер 30 днів не перепитує
й далі малює зі старого субсету. Наслідок: усі щойно додані іконки порожні.
"""
import glob
import io
import os
import re

import app as app_module
from app import get_assets_version

TEMPLATES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'templates')


# `url_for('static', filename='X')` … `?v={{ assets_version }}` -- саме та
# зв'язка, що робить файл версійованим. Хвіст між ними допускає атрибути й
# переноси рядка, але не інший url_for: інакше збіг перестрибнув би з одного
# посилання на ?v= сусіднього.
_VERSIONED_RE = re.compile(
    r"url_for\(\s*'static'\s*,\s*filename\s*=\s*'([^']+)'\s*\)"
    r"(?:(?!url_for).){0,40}?\?v=\s*\{\{\s*assets_version",
    re.S,
)


def _versioned_static_paths():
    """Шляхи static-файлів, підключених у шаблонах ключем ?v=assets_version."""
    found = set()
    for path in glob.glob(os.path.join(TEMPLATES, '**', '*.html'), recursive=True):
        with io.open(path, encoding='utf-8') as fh:
            found.update(_VERSIONED_RE.findall(fh.read()))
    return found


def _version(folder):
    """Версія для теки з нуля: глобальний кеш процесу скидається."""
    app_module._cached_assets_version = None
    try:
        return get_assets_version(str(folder))
    finally:
        app_module._cached_assets_version = None


def _static_tree(root):
    """Мінімальна static/ з усіма теками, які версіюються ключем ?v=."""
    for sub in ('css', 'js', 'fonts'):
        os.makedirs(root / sub, exist_ok=True)
    (root / 'css' / 'common.css').write_bytes(b'body{color:#000}')
    (root / 'js' / 'app.js').write_bytes(b'console.log(1)')
    (root / 'fonts' / 'material-symbols-rounded.woff2').write_bytes(b'FONT-A')
    return root


def test_font_change_moves_the_version(tmp_path):
    """Інакше оновлений субсет іконок залипає в immutable-кеші на 30 днів."""
    static = _static_tree(tmp_path / 'static')
    before = _version(static)

    (static / 'fonts' / 'material-symbols-rounded.woff2').write_bytes(b'FONT-B')

    assert _version(static) != before


def test_css_and_js_changes_still_move_the_version(tmp_path):
    """Стара поведінка лишається: правка css або js так само зриває кеш."""
    static = _static_tree(tmp_path / 'static')
    base = _version(static)

    (static / 'css' / 'common.css').write_bytes(b'body{color:#111}')
    after_css = _version(static)
    assert after_css != base

    (static / 'js' / 'app.js').write_bytes(b'console.log(2)')
    assert _version(static) != after_css


def test_version_is_stable_when_nothing_changed(tmp_path):
    """Ключ -- хеш ВМІСТУ: повторний розрахунок тієї самої теки дає те саме.

    Заради цього функція й рахує вміст, а не mtime: rsync-деплой оновлює час
    модифікації файлам, вміст яких не змінився, і кожен повторний відвідувач
    наново тягнув би всю статику.
    """
    static = _static_tree(tmp_path / 'static')
    assert _version(static) == _version(static)


def test_real_icon_font_is_covered_by_the_version(tmp_path):
    """Шрифт, який реально підключений у _icon_font.html, входить у ключ.

    Тест на живій теці app/static: якби fonts/ випав із розрахунку знову,
    підміна байтів справжнього субсету ключа б не зрушила.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    font = os.path.join(root, 'app', 'static', 'fonts',
                        'material-symbols-rounded.woff2')
    original = open(font, 'rb').read()
    before = _version(os.path.join(root, 'app', 'static'))
    try:
        open(font, 'wb').write(original + b'\x00')
        assert _version(os.path.join(root, 'app', 'static')) != before
    finally:
        open(font, 'wb').write(original)


def test_rendered_markup_asks_for_the_font_with_the_current_key(app):
    """Наскрізно: розмітка справді просить шрифт за поточним ключем.

    Юніт-тести вище доводять, що ключ рухається від правки шрифту. Цей --
    що шаблон бере саме його, а не захардкоджений чи окремий лічильник.
    Партіал підключений тільки з admin/base_admin.html, тож рендериться
    напряму: логін заради одного рядка розмітки тут нічого не додає.
    """
    import app as app_module
    from flask import render_template

    with app.test_request_context('/'):
        markup = render_template('partials/_icon_font.html')
    version = app_module.get_assets_version(app.static_folder)
    assert f'material-symbols-rounded.woff2?v={version}' in markup


def test_every_versioned_folder_is_hashed():
    """Кожен файл, підключений з ?v={{ assets_version }}, входить у розрахунок.

    ЦЕ ГОЛОВНИЙ ГАРД. Попередні тести ловлять поламаний розрахунок, цей --
    забуту теку: шаблон, що починає версіювати ключем нову теку, валить CI,
    доки її не додадуть у VERSIONED_ASSET_DIRS. Без нього файл мовчки залипає
    в immutable-кеші браузера на 30 днів, і побачить це лише той відвідувач,
    у якого стара версія вже осіла, -- на свіжому браузері все виглядає добре.
    """
    from app import VERSIONED_ASSET_DIRS

    covered = tuple((folder + '/', tuple(exts)) for folder, exts in VERSIONED_ASSET_DIRS)
    uncovered = []
    for path in _versioned_static_paths():
        match = [exts for prefix, exts in covered if path.startswith(prefix)]
        if not match:
            uncovered.append(f'{path} -- теки немає у VERSIONED_ASSET_DIRS')
        elif not path.lower().endswith(match[0]):
            uncovered.append(f'{path} -- розширення не входить у {match[0]}')

    assert not uncovered, (
        'Підключено з ?v=assets_version, але в ключ не входить:\n  '
        + '\n  '.join(sorted(uncovered))
    )


def test_the_guard_actually_scans_templates():
    """Сам сканер мусить щось знаходити: порожній результат зробив би гард
    вище вічнозеленим і непомітно марним."""
    paths = _versioned_static_paths()
    assert len(paths) >= 5
    assert 'fonts/material-symbols-rounded.woff2' in paths
