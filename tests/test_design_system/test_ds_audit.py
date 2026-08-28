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
