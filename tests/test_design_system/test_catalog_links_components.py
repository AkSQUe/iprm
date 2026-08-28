"""Каталог мусить підключати КОЖЕН компонентний CSS.

Інакше компонент неможливо побачити на вітрині -- а невидимий компонент
переписують у себе. Межа: файл компонентний, якщо має 2+ шаблони-споживачі
(транзитивно, через include/extends) -- див. tools/ds/ds_audit.py.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'ds'))

import ds_audit


def test_every_component_css_is_linked_in_catalog():
    gap = ds_audit.catalog_gap(ROOT)
    assert not gap, (
        'компонентні CSS не підключені до каталогу: ' + ', '.join(gap)
        + '\nДодайте <link> у app/templates/admin/design_system.html і '
          'покажіть компоненти в потрібному табі. Якщо файл насправді '
          'посторінковий -- у нього має бути один споживач.'
    )
