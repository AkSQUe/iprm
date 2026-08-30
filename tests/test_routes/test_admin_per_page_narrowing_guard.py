"""Джерельний вартовий пари per_page-поля й narrow_args-виключення.

Task 2 плану `docs/superpowers/plans/2026-08-30-admin-listing-tails.md` навчив
`empty_state` не рахувати per_page звуженням через `narrow_args={'per_page':
False}` -- але це рядок другого ключа в dict, що вже існував (`{'page': ...}`
у half із них), і майбутнє редагування («перепишемо page-bookmark-логіку»)
може стерти сусідній ключ, не помітивши. Макрос сам себе захистити не може:
він не знає, чи сторінка мала передати `'per_page': False`, доки їй не
дали шаблон із полем per_page.

Цей тест не рендерить жодної сторінки і не ходить у БД -- читає джерело
шаблонів напряму й звіряє два текстові маркери в КОЖНОМУ файлі
`app/templates/admin/*.html`:

  * `'name': 'per_page'`  -- filter_bar оголошує поле розміру сторінки;
  * `'per_page': False`   -- якийсь empty_state у тому самому файлі виключає
    його зі звуження.

Пара мусить бути ЦІЛА в обидва боки: є поле без виключення -- порожній зріз
під ?per_page=NN знову брехатиме "Нічого не знайдено"; є виключення без
поля -- маркер осиротів (поле перейменували чи прибрали, а виключення
лишилось привидом чи взагалі належить іншому реєстру). Параметризація йде
по ВСІХ файлах каталогу, тож дванадцята сторінка з per_page, яку хтось
додасть завтра, потрапляє в перевірку автоматично -- нового рядка в цьому
файлі не треба.
"""
from pathlib import Path

import pytest

ADMIN_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'admin'

PER_PAGE_FIELD_MARKER = "'name': 'per_page'"
PER_PAGE_EXCLUSION_MARKER = "'per_page': False"


def _admin_template_files():
    return sorted(ADMIN_TEMPLATES_DIR.glob('*.html'))


@pytest.mark.parametrize('path', _admin_template_files(), ids=lambda p: p.name)
def test_per_page_field_and_narrow_exclusion_are_paired(path):
    text = path.read_text(encoding='utf-8')
    has_field = PER_PAGE_FIELD_MARKER in text
    has_exclusion = PER_PAGE_EXCLUSION_MARKER in text

    if has_field and not has_exclusion:
        pytest.fail(
            f"{path.name}: filter_bar оголошує поле per_page, але жоден "
            "empty_state у файлі не передає narrow_args={'per_page': False} "
            "-- порожній зріз під ?per_page=NN знову друкуватиме "
            "'Нічого не знайдено' замість справжнього порожнього стану."
        )
    if has_exclusion and not has_field:
        pytest.fail(
            f"{path.name}: empty_state виключає 'per_page' зі звуження, але "
            "filter_bar у цьому файлі поля per_page взагалі не оголошує -- "
            "маркер осиротів (поле перейменували чи прибрали)."
        )
