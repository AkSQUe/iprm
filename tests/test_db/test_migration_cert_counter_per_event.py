"""Міграція cert_counter_per_event_20260929: лічильник на кожен захід.

Ризик -- у бекфілі. Занижений лічильник заходу дасть першій же новій видачі
зайнятий номер, завищений -- діру; тренерський діапазон зберігається зі
зсувом 100000, а лічильник -- без нього; легасі-номер іншої форми
(``IPRM-2026-000001``) має бути пропущений, а не впасти.

Тестова схема будується create_all з моделей, тож тут upgrade() проганяється
на окремій порожній SQLite-базі з мінімальними таблицями номерів.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / 'migrations' / 'versions' / 'cert_counter_per_event_20260929.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_cert_counter', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_counters_are_per_prefix_and_kind(migration):
    counters = migration.collect_counters(
        [
            '2026-2738-1028974-000001',
            '2026-2738-1028974-000006',
            '2026-2738-1031500-000007',
            '2026-2738-1031500-000012',
            'IPRM-2026-000001',
            None,
        ],
        ['2026-2738-1031500-100002', '2026-2738-1031500-100001'],
    )
    assert counters == {
        ('2026-2738-1028974', 'participant'): 6,
        ('2026-2738-1031500', 'participant'): 12,
        ('2026-2738-1031500', 'lecturer'): 2,
    }


def test_nothing_issued_gives_no_counters(migration):
    assert migration.collect_counters([], []) == {}


def test_upgrade_creates_and_backfills_the_table(migration, monkeypatch):
    engine = sa.create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(sa.text('CREATE TABLE certificates (number VARCHAR(40))'))
        conn.execute(sa.text('CREATE TABLE lecturer_certificates (number VARCHAR(40))'))
        conn.execute(sa.text(
            "INSERT INTO certificates VALUES ('2026-2738-1028974-000006'), "
            "('2026-2738-1031500-000012')"))
        conn.execute(sa.text(
            "INSERT INTO lecturer_certificates VALUES ('2026-2738-1031500-100001')"))

        ops = Operations(MigrationContext.configure(conn))
        monkeypatch.setattr(migration, 'op', ops)
        migration.upgrade()

        rows = conn.execute(sa.text(
            'SELECT prefix, kind, last_value FROM certificate_number_counters '
            'ORDER BY prefix, kind')).fetchall()

    assert [tuple(r) for r in rows] == [
        ('2026-2738-1028974', 'participant', 6),
        ('2026-2738-1031500', 'lecturer', 1),
        ('2026-2738-1031500', 'participant', 12),
    ]


def test_offset_matches_the_model(migration):
    from app.models.lecturer_certificate import LECTURER_NUMBER_OFFSET
    assert migration.LECTURER_NUMBER_OFFSET == LECTURER_NUMBER_OFFSET
