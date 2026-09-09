"""Міграція bpr_event_types_20260909: сидінг довідника.

DDL тут не проганяємо -- у тестовій схемі (create_all з моделей) таблиця
вже є. Перевіряємо те, де справді можна помилитись: список рядків, який
міграція вставляє, мусить збігатися з канонічним SEED_ROWS моделі.
Розійдуться -- прод отримає одне наповнення, а тести інше.
"""
import importlib.util
from pathlib import Path

import pytest

from app.models.event_type import SEED_ROWS

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / 'migrations' / 'versions' / 'bpr_event_types_20260909.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_bpr_event_types', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_seed_matches_model_seed(migration):
    def key(rows):
        return sorted(
            (r['code'], r['name'], r['name_accusative'],
             r['name_genitive'], r['sort_order'], r['is_active'])
            for r in rows
        )

    assert key(migration.SEED_ROWS) == key(SEED_ROWS)


def test_migration_declares_current_head(migration):
    assert migration.down_revision == 'transfer_after_days_20260908'
    assert migration.revision == 'bpr_event_types_20260909'
