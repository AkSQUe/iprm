"""Міграція paid_at_precision_20261008: точність дати оплати.

Ризик -- у правилі бекфілу. 'date' мусить отримати лише умовний полудень
за Києвом (результат paid_moment для минулої дати), а не будь-який час,
інакше справжній момент LiqPay-оплати назвемо невідомим. І кожен змінений
рядок мусить отримати свіжий updated_at: MM Medic тягне зміни за
updated_since.

Тестова схема будується create_all з моделей, тож upgrade() проганяється
на окремій порожній SQLite-базі з мінімальними таблицями.
"""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.mixins import PAID_AT_PRECISIONS, paid_at_precision_sql

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / 'migrations' / 'versions' / 'paid_at_precision_20261008.py'
)
KYIV = ZoneInfo('Europe/Kyiv')


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_paid_at_precision', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_noon_kyiv_is_date(migration):
    assert migration.precision_for(datetime(2026, 9, 15, 12, tzinfo=KYIV)) == 'date'


def test_noon_kyiv_in_winter_is_date(migration):
    """Зсув Києва взимку інший (UTC+2): правило дивиться на київський час."""
    assert migration.precision_for(datetime(2026, 1, 15, 10, tzinfo=timezone.utc)) == 'date'


@pytest.mark.parametrize('moment', [
    datetime(2026, 9, 15, 12, 0, 0, 1, tzinfo=KYIV),
    datetime(2026, 9, 15, 12, 0, 1, tzinfo=KYIV),
    datetime(2026, 9, 15, 12, tzinfo=timezone.utc),
    datetime(2026, 9, 15, 0, tzinfo=KYIV),
])
def test_any_other_time_is_datetime(migration, moment):
    assert migration.precision_for(moment) == 'datetime'


def test_sqlite_string_without_zone_is_utc(migration):
    assert migration.precision_for('2026-09-15 09:00:00.000000') == 'date'
    assert migration.precision_for('2026-09-15 09:00:00.000123') == 'datetime'


def test_check_matches_the_model(migration):
    """Міграція не імпортує застосунок, тож умову продубльовано -- і вона
    мусить лишатися тією самою, що в моделі."""
    assert migration.CHECK_SQL == paid_at_precision_sql()
    assert (migration.PRECISION_DATETIME, migration.PRECISION_DATE) == PAID_AT_PRECISIONS


def test_upgrade_backfills_and_bumps_updated_at(migration, monkeypatch):
    old = '2026-09-20 08:00:00.000000'
    engine = sa.create_engine('sqlite://')
    with engine.begin() as conn:
        for table in ('event_registrations', 'online_enrollments'):
            conn.execute(sa.text(
                f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, '
                'paid_at DATETIME, updated_at DATETIME)'))
        conn.execute(sa.text(
            'INSERT INTO event_registrations VALUES '
            f"(1, '2026-09-15 09:00:00.000000', '{old}'), "
            f"(2, '2026-09-15 09:13:27.481000', '{old}'), "
            f"(3, NULL, '{old}')"))
        conn.execute(sa.text(
            'INSERT INTO online_enrollments VALUES '
            f"(1, '2026-09-16 09:00:00.000000', '{old}')"))

        ops = Operations(MigrationContext.configure(conn))
        monkeypatch.setattr(migration, 'op', ops)
        migration.upgrade()

        regs = conn.execute(sa.text(
            'SELECT id, paid_at_precision, updated_at FROM event_registrations '
            'ORDER BY id')).fetchall()
        enrollment = conn.execute(sa.text(
            'SELECT paid_at_precision FROM online_enrollments')).scalar()

    assert [(r.id, r.paid_at_precision) for r in regs] == [
        (1, 'date'), (2, 'datetime'), (3, None),
    ]
    assert regs[0].updated_at != old and regs[1].updated_at != old
    assert regs[2].updated_at == old
    assert enrollment == 'date'
