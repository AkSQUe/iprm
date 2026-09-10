"""Ключ ?v= мусить мінятись від БУДЬ-ЯКОГО статичного файлу, який ним версіюють.

Регресія: get_assets_version() хешувала лише static/css/*.css і static/js/*.js,
а шрифт іконок (static/fonts/material-symbols-rounded.woff2) підключений тим
самим ?v={{ assets_version }} у partials/_icon_font.html. Перегенерація субсету
без правки css/js лишала ключ незмінним, а nginx віддає /static/ з
`expires 30d; Cache-Control: public, immutable` -- браузер 30 днів не перепитує
й далі малює зі старого субсету. Наслідок: усі щойно додані іконки порожні.
"""
import os

import app as app_module
from app import get_assets_version


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
