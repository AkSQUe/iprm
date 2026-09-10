from decimal import Decimal

import pytest

from app.i18n_plurals import points_text
from app.utils import format_points, parse_points


@pytest.mark.parametrize('raw, expected', [
    ('4,5', Decimal('4.50')),
    ('4.5', Decimal('4.50')),
    ('9', Decimal('9.00')),
    (' 7,5 ', Decimal('7.50')),
    (4.5, Decimal('4.50')),
    (Decimal('4.5'), Decimal('4.50')),
])
def test_parse_points_accepts_both_separators(raw, expected):
    assert parse_points(raw) == expected


@pytest.mark.parametrize('raw', [None, '', '   '])
def test_parse_points_empty_is_none(raw):
    assert parse_points(raw) is None


@pytest.mark.parametrize('raw', ['abc', '4,5,6', '--1'])
def test_parse_points_rejects_garbage(raw):
    with pytest.raises(ValueError):
        parse_points(raw)


@pytest.mark.parametrize('raw', ['1e30', '9' * 32])
def test_parse_points_rejects_overflow_as_value_error(raw):
    # quantize() кидає decimal.InvalidOperation на завеликому числі -- це
    # ArithmeticError, НЕ ValueError, і виклики (форми, xlsx-імпорт,
    # підтвердження присутності) ловлять лише ValueError. Без явного
    # перетворення в parse_points сюрприз був би 500-ю.
    with pytest.raises(ValueError):
        parse_points(raw)


@pytest.mark.parametrize('value, expected', [
    (Decimal('9.00'), '9'),
    (Decimal('7.50'), '7,5'),
    (Decimal('4.55'), '4,55'),
    (Decimal('100.00'), '100'),
    (None, ''),
])
def test_format_points_trims_trailing_zeros(value, expected):
    assert format_points(value) == expected


def test_format_points_custom_separator():
    assert format_points(Decimal('7.50'), sep='.') == '7.5'


def test_points_text_uses_dot_for_english(app):
    from flask_babel import force_locale
    with app.test_request_context('/'):
        with force_locale('en'):
            assert points_text(Decimal('7.50')) == '7.5'
        with force_locale('uk'):
            assert points_text(Decimal('7.50')) == '7,5'
