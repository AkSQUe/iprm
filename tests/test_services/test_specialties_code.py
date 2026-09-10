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


def test_normalize_name_treats_apostrophe_variants_as_equal():
    # U+2019 (’, як у номенклатурі) і ASCII U+0027 ('), як хтось набирає з
    # клавіатури -- мають нормалізуватись до однієї й тієї ж форми, інакше
    # бекфіл міграції заводить рядок-дублікат замість того, щоб впізнати
    # вже наявний код довідника (Громадське здоров’я / Громадське здоров'я).
    assert normalize_name('Громадське здоров’я') == normalize_name("Громадське здоров'я")


def test_normalize_name_treats_modifier_apostrophe_as_equal():
    # U+02BC (ʼ, модифікатор-апостроф) -- третій варіант, який теж трапляється
    # у вільному тексті.
    assert normalize_name('Громадське здоровʼя') == normalize_name("Громадське здоров'я")
