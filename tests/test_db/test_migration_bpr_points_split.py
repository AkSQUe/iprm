"""Міграція bpr_points_split_20260909.

Саму upgrade() тут не проганяємо: у тестовій схемі (create_all з моделей)
нові колонки вже є, тож add_column упав би на дублікаті. Перевіряємо те, що
справді може піти не так, -- перенесення даних.
"""
import importlib.util
from pathlib import Path

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
    / 'bpr_points_split_20260909_add_format_columns.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_points_split', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_copies_old_value_into_both_columns(migration):
    for table in ('courses', 'course_instances'):
        sql = migration.copy_points_sql(table)
        assert 'cpd_points_online = cpd_points' in sql
        assert 'cpd_points_offline = cpd_points' in sql
        assert table in sql


def test_backfill_takes_format_from_tariff(migration):
    sql = migration.participation_format_backfill_sql()
    assert 'instance_tariffs' in sql
    assert 'event_format' in sql
    # Тільки задані формати: NULL у тарифі не має ставати рядком.
    assert "IN ('online', 'offline')" in sql


def test_downgrade_keeps_offline_value(migration):
    sql = migration.collapse_points_sql('courses')
    assert 'cpd_points = cpd_points_offline' in sql
