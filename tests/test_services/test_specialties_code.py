"""Код рядка довідника спеціальностей: транслітерація, унікальність, довжина."""
from app.services.specialties import CODE_MAX_LENGTH, normalize_name, specialty_code


def test_code_is_latin_slug_of_ukrainian_name():
    assert specialty_code('Дитяча ендокринологія') == 'dytiacha-endokrynolohiia'


def test_code_collapses_separators():
    assert specialty_code('Загальна практика - сімейна медицина') == \
        'zahalna-praktyka-simeina-medytsyna'


def test_code_gets_suffix_when_taken():
    # "Бактеріологія" є і серед лікарських, і серед професіоналів.
    taken = {'bakteriolohiia'}
    assert specialty_code('Бактеріологія', taken=taken) == 'bakteriolohiia-2'


def test_code_suffix_repeats_until_free():
    taken = {'bakteriolohiia', 'bakteriolohiia-2'}
    assert specialty_code('Бактеріологія', taken=taken) == 'bakteriolohiia-3'


def test_code_fits_column():
    long_name = 'Лабораторні дослідження факторів навколишнього середовища людини'
    code = specialty_code(long_name)
    assert len(code) <= CODE_MAX_LENGTH
    assert not code.endswith('-')


def test_normalize_name_ignores_case_and_spacing():
    assert normalize_name('  Усі   Лікарські  Спеціальності ') == 'усі лікарські спеціальності'
