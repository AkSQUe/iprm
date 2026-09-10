"""Локалізована плюралізація (app.i18n_plurals.plural)."""
from decimal import Decimal

import pytest

from app.i18n_plurals import PLURAL_FORMS, plural
from app.utils import uk_plural


@pytest.mark.parametrize('n,expected', [
    (1, 'бал БПР'), (2, 'бали БПР'), (4, 'бали БПР'),
    (5, 'балів БПР'), (0, 'балів БПР'), (11, 'балів БПР'),
    (21, 'бал БПР'), (22, 'бали БПР'), (25, 'балів БПР'),
])
def test_uk_slavic_forms(n, expected):
    assert plural(n, 'bpr_points', lang='uk') == expected


@pytest.mark.parametrize('n,expected', [
    (1, 'балл БПР'), (2, 'балла БПР'), (5, 'баллов БПР'),
])
def test_ru_slavic_forms(n, expected):
    assert plural(n, 'bpr_points', lang='ru') == expected


@pytest.mark.parametrize('n,expected', [
    (1, 'BPR point'), (2, 'BPR points'), (5, 'BPR points'), (0, 'BPR points'),
])
def test_en_two_forms(n, expected):
    assert plural(n, 'bpr_points', lang='en') == expected


def test_unknown_key_returns_key():
    assert plural(3, 'nope', lang='uk') == 'nope'


def test_non_numeric_falls_back():
    assert plural(None, 'seats', lang='uk') == 'місць'


def test_unknown_lang_falls_back_to_uk():
    assert plural(2, 'seats', lang='fr') == 'місця'


def test_every_key_has_all_languages():
    fraction_keys = {'bpr_points', 'points'}
    for key, langs in PLURAL_FORMS.items():
        assert set(langs) >= {'uk', 'ru', 'en'}, key
        expected = 4 if key in fraction_keys else 3
        assert len(langs['uk']) == expected and len(langs['ru']) == expected, key
        assert len(langs['en']) == 2


def test_filter_uses_active_locale(app):
    from flask_babel import force_locale
    with app.app_context():
        with force_locale('ru'):
            assert plural(5, 'seats') == 'мест'
        with force_locale('uk'):
            assert plural(5, 'seats') == 'місць'


def test_plural_fraction_uses_genitive_singular():
    assert plural(Decimal('4.5'), 'bpr_points', lang='uk') == 'бала БПР'
    assert plural(Decimal('7.5'), 'points', lang='uk') == 'бала'
    assert plural(Decimal('4.5'), 'bpr_points', lang='ru') == 'балла БПР'


def test_plural_whole_numbers_unchanged():
    assert plural(1, 'bpr_points', lang='uk') == 'бал БПР'
    assert plural(3, 'bpr_points', lang='uk') == 'бали БПР'
    assert plural(9, 'bpr_points', lang='uk') == 'балів БПР'


def test_plural_fraction_in_two_form_language():
    assert plural(Decimal('7.5'), 'bpr_points', lang='en') == 'BPR points'


def test_plural_fraction_without_fourth_form_falls_back_to_many():
    assert plural(Decimal('2.5'), 'seats', lang='uk') == 'місць'


def test_unparsable_falls_back_to_many_not_fraction():
    """Остання форма набору тепер дробова, тож `forms[-1]` як запасна дала б
    «бала БПР» на будь-якому смітті. Запасна мусить лишатись «багато»."""
    assert plural(None, 'bpr_points', lang='uk') == 'балів БПР'
    assert plural('abc', 'points', lang='uk') == 'балів'
    assert plural(None, 'seats', lang='uk') == 'місць'


def test_uk_plural_fraction():
    assert uk_plural(Decimal('4.5'), 'бал', 'бали', 'балів', 'бала') == 'бала'
    assert uk_plural(Decimal('4.5'), 'бал', 'бали', 'балів') == 'балів'
    assert uk_plural(2, 'бал', 'бали', 'балів', 'бала') == 'бали'
