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


# Семантика суб'єкта селектора -- пришпилено на літеральних рядках CSS, а
# не на живих файлах проєкту: файли зміняться, а правило "суб'єкт -- це
# останній компаунд, поза дужками псевдокласів" мусить лишатись перевіреним
# незалежно від того, що зараз лежить у app/static/css.

def test_selector_subject_ignores_functional_pseudo_class_argument():
    subjects = ds_audit._selector_subject_classes(
        '.admin-sidebar__link:has(.badge)::after '
    )
    assert subjects == {'admin-sidebar__link'}, (
        ".badge -- аргумент :has(), а не суб'єкт: правило не перестилізовує "
        ".badge, воно лише УМОВНО спрацьовує, коли всередині є .badge."
    )


def test_selector_subject_is_last_compound_of_descendant_selector():
    subjects = ds_audit._selector_subject_classes('.admin-instances-place .badge ')
    assert subjects == {'badge'}, (
        ".admin-instances-place -- предок у descendant-селекторі, не "
        "суб'єкт; .badge -- останній компаунд, саме його стилізує правило."
    )


def test_selector_subject_compound_selector_keeps_every_class_in_it():
    subjects = ds_audit._selector_subject_classes('.card.card--wide ')
    assert subjects == {'card', 'card--wide'}, (
        'card і card--wide стоять в ОДНОМУ компаунді (без комбінатора між '
        'ними) -- обидва суб’єкт цього правила.'
    )


def test_selector_subject_child_combinator_drops_the_parent():
    subjects = ds_audit._selector_subject_classes('.card > .card__title ')
    assert subjects == {'card__title'}, (
        '.card -- предок через дочірній комбінатор >, не суб’єкт.'
    )


def test_selector_subject_comma_list_splits_into_independent_selectors():
    subjects = ds_audit._selector_subject_classes('.foo, .bar ')
    assert subjects == {'foo', 'bar'}


def test_selector_subject_catches_naive_regression():
    """Наївний розбір (усі класи в селекторі, без урахування суб'єкта) дав
    би тут {'foo', 'bar', 'baz', 'qux'}. Цей тест падає, якщо хтось
    поверне такий підрахунок замість суб'єктного.
    """
    subjects = ds_audit._selector_subject_classes(
        '.foo:not(.bar):has(.baz) .qux '
    )
    assert subjects == {'qux'}
