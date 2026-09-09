"""Читальна частина довідника: порядок, локалізація, вибір для форми."""
import pytest

from app.extensions import db
from app.models.specialty import Specialty
from app.services import specialties


@pytest.fixture
def catalog_rows():
    rows = [
        Specialty(code='all-medical', name='усі лікарські спеціальності',
                  section='medical', is_group=True, sort_order=0),
        Specialty(code='dermatovenerolohiia', name='Дерматовенерологія',
                  section='medical', sort_order=6),
        Specialty(code='alerholohiia', name='Алергологія',
                  section='medical', sort_order=2),
        Specialty(code='farmatsiia', name='Фармація',
                  section='pharmacy', sort_order=5),
        Specialty(code='stara-nazva', name='Стара назва',
                  section='medical', sort_order=99, is_active=False),
    ]
    db.session.add_all(rows)
    db.session.commit()
    return rows


def test_names_follow_nomenclature_order(app, catalog_rows):
    with app.test_request_context('/'):
        assert specialties.names(['dermatovenerolohiia', 'alerholohiia']) == \
            ['Алергологія', 'Дерматовенерологія']


def test_names_ignore_unknown_codes(app, catalog_rows):
    with app.test_request_context('/'):
        assert specialties.names(['alerholohiia', 'no-such-code']) == ['Алергологія']


def test_line_joins_with_comma(app, catalog_rows):
    with app.test_request_context('/'):
        assert specialties.line(['alerholohiia', 'dermatovenerolohiia']) == \
            'Алергологія, Дерматовенерологія'


def test_line_is_none_when_empty(app, catalog_rows):
    with app.test_request_context('/'):
        assert specialties.line([]) is None


def test_names_use_translation(app, catalog_rows):
    row = Specialty.query.filter_by(code='alerholohiia').one()
    row.set_translation('ru', 'name', 'Аллергология')
    db.session.commit()
    with app.test_request_context('/ru/'):
        # Голий test_request_context не проганяє url_value_preprocessor
        # (app/i18n.py:pull_lang_code), тож g.lang_code лишається порожнім
        # і get_locale() падає на дефолт 'uk' -- як і в
        # tests/test_i18n/test_js_strings.py::test_js_dict_translated_for_ru,
        # ставимо мову вручну.
        from flask import g
        g.lang_code = 'ru'
        assert specialties.names(['alerholohiia']) == ['Аллергология']


def test_choices_group_by_section_and_skip_inactive(app, catalog_rows):
    with app.test_request_context('/'):
        groups = dict(specialties.choices())
    assert [code for code, _label in groups['Лікарські']] == \
        ['all-medical', 'alerholohiia', 'dermatovenerolohiia']
    assert 'stara-nazva' not in [code for code, _ in groups['Лікарські']]


def test_choices_keep_current_even_if_deactivated(app, catalog_rows):
    with app.test_request_context('/'):
        groups = dict(specialties.choices(current=['stara-nazva']))
    assert 'stara-nazva' in [code for code, _label in groups['Лікарські']]


def test_valid_codes_contains_inactive_rows(app, catalog_rows):
    with app.test_request_context('/'):
        assert 'stara-nazva' in specialties.valid_codes()
