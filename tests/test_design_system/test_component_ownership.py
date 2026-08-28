"""Компонент оголошується один раз -- інакше правка до сторінки не доходить.

Клас, оголошений у двох файлах, перебивається тим, що підключений пізніше.
Саме через це правка `apple-btn` у дизайн-системі сьогодні не змінює кнопку
на /courses: page-courses.css переоголошує її в себе.

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
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    current = ds_audit.duplicate_classes(ROOT)
    fresh = sorted(set(current) - set(baseline))
    assert not fresh, (
        'нові класи з двома власниками: ' + ', '.join(
            '.%s (%s)' % (c, ', '.join(current[c])) for c in fresh)
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
