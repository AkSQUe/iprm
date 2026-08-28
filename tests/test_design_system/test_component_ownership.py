"""Компонент оголошується один раз -- інакше правка до сторінки не доходить.

Клас, оголошений у двох файлах, перебивається тим, що підключений пізніше.
Саме через це правка `apple-btn` у дизайн-системі сьогодні не змінює кнопку
на /courses: courses.css переоголошує її в себе.

Тест -- ХРАПОВИК, а не вимога нуля: 69 наявних дублікатів закриваються
окремими етапами, а тест не дає з'явитись 81-му. Коли дублікат прибрано,
baseline перезаписується `python tools/ds/ds_audit.py --write-baseline`;
інструмент відмовиться це зробити, якщо число зросло.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'ds'))

import ds_audit

BASELINE = Path(__file__).parent / 'duplicate_classes_baseline.json'


def test_no_new_duplicate_classes():
    """Порівнює не МНОЖИНИ ІМЕН класів, а власників кожного класу.

    `set(current) - set(baseline)` бачить лише 70-й НОВИЙ клас: для всіх 69
    класів, що вже є в baseline, множина імен не міняється, навіть якщо в
    когось із них з'явився ТРЕТІЙ файл-власник -- обмін "прибрав один --
    завів інший" минав повз стару перевірку мовчки.
    """
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    current = ds_audit.duplicate_classes(ROOT)
    fresh = ds_audit.new_duplicate_owners(current, baseline)
    assert not fresh, (
        'нові власники дублікатів: ' + ', '.join(
            '.%s -> %s' % (c, ', '.join(files)) for c, files in sorted(fresh.items()))
        + '\nКомпонент мусить бути оголошений ОДИН раз -- інакше правка в '
          'дизайн-системі не дійде до сторінки, що його переоголосила. '
          'Візьміть наявний компонент (перелік -- на /admin/design-system) '
          'або винесіть свій у компонентний файл.'
    )


def test_baseline_only_shrinks():
    """Прибрали дублікат -- перезапишіть baseline; він не має рости."""
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    current = ds_audit.duplicate_classes(ROOT)
    assert len(current) <= len(baseline), (
        'дублікатів стало більше: %d проти %d у baseline'
        % (len(current), len(baseline))
    )


# Синтетичні дані -- не живі файли проєкту: доводять саме те, що зламалось
# у C1, а не залежать від того, що зараз лежить у app/static/css.

def test_new_duplicate_owners_ignores_same_owner_set():
    """Той самий клас із тими самими власниками -- не новина, тест зелений."""
    baseline = {'apple-btn': ['common.css', 'courses.css']}
    current = {'apple-btn': ['common.css', 'courses.css']}
    assert ds_audit.new_duplicate_owners(current, baseline) == {}


def test_new_duplicate_owners_catches_owner_swap_without_count_change():
    """Доведення C1: 'прибрав одного власника -- завів іншого' не змінює
    len(dupes) (2 і там, і там), тому старий тест (порівняння множин ІМЕН
    класів чи їхньої кількості) це пропускав. Клас той самий, кількість
    власників та сама -- але один із власників НОВИЙ, і саме це мусить
    впасти.
    """
    baseline = {'apple-btn': ['common.css', 'courses.css']}
    current = {'apple-btn': ['common.css', 'page-contact.css']}
    fresh = ds_audit.new_duplicate_owners(current, baseline)
    assert fresh == {'apple-btn': ['page-contact.css']}, (
        'новий власник .apple-btn -- page-contact.css -- мусить бути '
        'названий поіменно, а courses.css (зниклий власник) не вважається '
        'новиною.'
    )


def test_new_duplicate_owners_catches_brand_new_class():
    """70-й НОВИЙ клас (якого в baseline не було взагалі) теж мусить впасти
    -- це вже ловила стара перевірка, і нова не повинна це втратити.
    """
    baseline = {'apple-btn': ['common.css', 'courses.css']}
    current = {
        'apple-btn': ['common.css', 'courses.css'],
        'apple-tag': ['common.css', 'page-contact.css'],
    }
    fresh = ds_audit.new_duplicate_owners(current, baseline)
    assert fresh == {'apple-tag': ['common.css', 'page-contact.css']}
