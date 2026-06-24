"""Guard tests for the self-hosted Material Symbols icon system.

Захищають виправлення «зламаних іконок на мобільному»: іконки мають лишатись
self-hosted (без Google CDN), субсет-шрифт -- малим і синхронним із мапою
ICON_CODEPOINTS, а всі icon('<name>') у шаблонах -- присутні в мапі та шрифті.
Чистий Python -- без браузера, працює у звичайному pytest CI.
"""
import os
import re
import glob

import pytest

from app.icons import ICON_CODEPOINTS, render_icon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, 'app', 'templates')
FONT = os.path.join(ROOT, 'app', 'static', 'fonts', 'material-symbols-rounded.woff2')

ICON_CALL_RE = re.compile(r"icon\('([a-z0-9_]+)'")


def _all_templates():
    return glob.glob(os.path.join(TEMPLATES, '**', '*.html'), recursive=True)


def _used_icon_names():
    names = set()
    for f in _all_templates():
        names.update(ICON_CALL_RE.findall(open(f, encoding='utf-8').read()))
    return names


def test_no_google_material_symbols_cdn():
    """Жоден шаблон не повертає завантаження іконок з Google CDN."""
    offenders = []
    for f in _all_templates():
        if 'Material+Symbols' in open(f, encoding='utf-8').read():
            offenders.append(os.path.relpath(f, ROOT))
    assert not offenders, 'Google Material Symbols CDN re-added in: %s' % offenders


def test_served_font_is_subset():
    """Served-шрифт існує і малий (субсет, а не повний ~407 КБ)."""
    assert os.path.exists(FONT), 'subset font missing'
    size = os.path.getsize(FONT)
    assert size < 50_000, 'font too large (%d bytes) -- did the full font slip in?' % size


def test_all_used_icons_in_map():
    """Кожен icon('<name>') у шаблонах присутній у ICON_CODEPOINTS."""
    missing = sorted(n for n in _used_icon_names() if n not in ICON_CODEPOINTS)
    assert not missing, 'icon names used in templates but absent from ICON_CODEPOINTS: %s' % missing


def test_map_in_sync_with_font():
    """Кожен кодпойнт із ICON_CODEPOINTS реально присутній у субсет-шрифті.

    Ловить розсинхрон (додали в мапу, але не перезапустили scripts/subset-icons.py)."""
    from fontTools.ttLib import TTFont
    font = TTFont(FONT)
    cmap = font.getBestCmap()
    missing = sorted(
        '%s(0x%x)' % (n, cp) for n, cp in ICON_CODEPOINTS.items() if cp not in cmap
    )
    assert not missing, 'codepoints in map but not in subset font: %s' % missing


def test_render_icon_decorative_by_default():
    out = str(render_icon('edit'))
    assert 'material-symbols-rounded' in out
    assert 'aria-hidden="true"' in out
    assert '&#x%x;' % ICON_CODEPOINTS['edit'] in out


def test_render_icon_with_label_is_accessible():
    out = str(render_icon('visibility', label='Переглянути'))
    assert 'role="img"' in out
    assert 'aria-label="Переглянути"' in out
    assert 'aria-hidden' not in out


def test_render_icon_extra_class():
    out = str(render_icon('event', cls='admin-empty__icon'))
    assert 'class="material-symbols-rounded admin-empty__icon"' in out


def test_render_icon_unknown_is_empty():
    assert str(render_icon('definitely_not_an_icon')) == ''
