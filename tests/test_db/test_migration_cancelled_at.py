"""Міграція cancelled_at_20261010: дата скасування для вже скасованих.

Ризик -- у наповненні: дата, що лягла не в той місяць, переносить утриману
частину оплати в чужий фінзвіт. Порядок джерел -- повне повернення, рішення
за заявкою, остання правка рядка; нескасованим дата не ставиться.

Тестова схема будується create_all з моделей, тож тут upgrade() проганяється
на окремій порожній SQLite-базі з мінімальними таблицями.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / 'migrations' / 'versions' / 'cancelled_at_20261010.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_cancelled_at', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cancelled_at(conn, table):
    return dict(conn.execute(sa.text(
        f'SELECT id, cancelled_at FROM {table} ORDER BY id')).fetchall())


def test_upgrade_backfills_best_known_date(migration, monkeypatch):
    engine = sa.create_engine('sqlite://')
    with engine.begin() as conn:
        for table in ('event_registrations', 'online_enrollments'):
            conn.execute(sa.text(
                f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, status VARCHAR(20), '
                'refunded_at DATETIME, updated_at DATETIME, created_at DATETIME)'))
        conn.execute(sa.text(
            'CREATE TABLE refund_requests (id INTEGER PRIMARY KEY, '
            'registration_id INTEGER, enrollment_id INTEGER, status VARCHAR(20), '
            'decided_at DATETIME)'))
        conn.execute(sa.text(
            "INSERT INTO event_registrations VALUES "
            # повне повернення -- точна дата
            "(1, 'cancelled', '2026-09-10 10:00:00', '2026-10-01 00:00:00', '2026-08-01'),"
            # заявку задоволено без грошей
            "(2, 'cancelled', NULL, '2026-10-01 00:00:00', '2026-08-01'),"
            # скасовано вручну -- лише остання правка
            "(3, 'cancelled', NULL, '2026-09-20 00:00:00', '2026-08-01'),"
            # не скасовано -- дати немає
            "(4, 'confirmed', '2026-09-10 10:00:00', '2026-09-20 00:00:00', '2026-08-01')"))
        conn.execute(sa.text(
            "INSERT INTO online_enrollments VALUES "
            "(1, 'cancelled', NULL, '2026-09-25 00:00:00', '2026-08-01')"))
        conn.execute(sa.text(
            "INSERT INTO refund_requests VALUES "
            "(1, 2, NULL, 'approved', '2026-09-15 12:00:00'),"
            "(2, 2, NULL, 'rejected', '2026-09-30 12:00:00'),"
            "(3, NULL, 1, 'approved', '2026-09-05 08:00:00')"))

        ops = Operations(MigrationContext.configure(conn))
        monkeypatch.setattr(migration, 'op', ops)
        migration.upgrade()

        regs = _cancelled_at(conn, 'event_registrations')
        online = _cancelled_at(conn, 'online_enrollments')

    assert str(regs[1]).startswith('2026-09-10 10:00')
    assert str(regs[2]).startswith('2026-09-15 12:00')
    assert str(regs[3]).startswith('2026-09-20')
    assert regs[4] is None
    assert str(online[1]).startswith('2026-09-05 08:00')
