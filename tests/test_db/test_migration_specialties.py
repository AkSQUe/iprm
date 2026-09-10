"""Міграція specialties_20260909: чисті хелпери бекфілу.

upgrade()/downgrade() тут не проганяємо (як і в
test_migration_bpr_points_split.py) -- у тестовій схемі таблиця specialties
вже створена моделями, і create_table упав би на дублікаті. Перевіряємо
логіку, яку можна виділити в чисту функцію без БД.
"""
import importlib.util
from pathlib import Path

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
    / 'specialties_20260909.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_specialties', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _normalize(name):
    return ' '.join((name or '').split()).lower()


def test_name_to_code_map_prefers_lower_section_position(app, migration):
    """27 назв номенклатури повторюються у двох розділах ("Педіатрія",
    "Бактеріологія" тощо). Без ORDER BY у SELECT рядки могли прийти в
    будь-якому порядку -- і незалежно від нього переможцем має лишатись код
    із МЕНШОЮ позицією розділу за SECTIONS (лікарські важать більше за
    фахівців)."""
    rows_medical_first = [
        ('bakteriolohiia-medical', 'Бактеріологія', 'medical'),
        ('bakteriolohiia-specialists', 'Бактеріологія', 'specialists'),
    ]
    rows_specialists_first = list(reversed(rows_medical_first))

    for rows in (rows_medical_first, rows_specialists_first):
        mapping = migration._name_to_code_map(rows, _normalize)
        assert mapping[_normalize('Бактеріологія')] == 'bakteriolohiia-medical'


def test_name_to_code_map_keeps_unique_names(app, migration):
    rows = [
        ('alerholohiia', 'Алергологія', 'medical'),
        ('farmatsiia', 'Фармація', 'pharmacy'),
    ]
    mapping = migration._name_to_code_map(rows, _normalize)
    assert mapping == {
        _normalize('Алергологія'): 'alerholohiia',
        _normalize('Фармація'): 'farmatsiia',
    }


def test_name_to_code_map_unknown_section_loses_to_known(app, migration):
    """Рядок з незнаною секцією трактується як найгірша позиція -- відомий
    розділ номенклатури завжди переважає."""
    rows = [
        ('mystery', 'Загадка', 'no-such-section'),
        ('specialists-mystery', 'Загадка', 'specialists'),
    ]
    mapping = migration._name_to_code_map(rows, _normalize)
    assert mapping[_normalize('Загадка')] == 'specialists-mystery'
