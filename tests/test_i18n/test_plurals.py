"""Локалізована плюралізація (app.i18n_plurals.plural)."""
import pytest

from app.i18n_plurals import PLURAL_FORMS, plural


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
    for key, langs in PLURAL_FORMS.items():
        assert set(langs) >= {'uk', 'ru', 'en'}, key
        assert len(langs['uk']) == 3 and len(langs['ru']) == 3
        assert len(langs['en']) == 2


def test_filter_uses_active_locale(app):
    from flask_babel import force_locale
    with app.app_context():
        with force_locale('ru'):
            assert plural(5, 'seats') == 'мест'
        with force_locale('uk'):
            assert plural(5, 'seats') == 'місць'
