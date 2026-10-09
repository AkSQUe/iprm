"""Міграція drop_cert_global_ctr_20261009: колонки йдуть, відкат їх повертає.

Ризик -- у downgrade: повернутий загальний лічильник має бути не меншим за
найбільший виданий сегмент, інакше стара нумерація після відкату почала б
видавати вже зайняті номери. Тестова схема будується create_all з моделей
(колонок там уже немає), тож міграція проганяється на окремій SQLite-базі.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / 'migrations' / 'versions' / 'drop_cert_global_ctr_20261009.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_drop_cert_ctr', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def conn():
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text(
            'CREATE TABLE site_settings (id INTEGER PRIMARY KEY, '
            "bpr_provider_number VARCHAR(20) NOT NULL DEFAULT '', "
            "bpr_participant_counter INTEGER NOT NULL DEFAULT '0', "
            "bpr_lecturer_counter INTEGER NOT NULL DEFAULT '0')"))
        connection.execute(sa.text(
            "INSERT INTO site_settings (id, bpr_provider_number) VALUES (1, '2738')"))
        connection.execute(sa.text('CREATE TABLE certificates (number VARCHAR(40))'))
        connection.execute(sa.text(
            'CREATE TABLE lecturer_certificates (number VARCHAR(40))'))
        connection.execute(sa.text(
            "INSERT INTO certificates VALUES ('2026-2738-1028974-000006'), "
            "('2026-2738-1031500-000003'), ('IPRM-2026-000001')"))
        connection.execute(sa.text(
            "INSERT INTO lecturer_certificates VALUES ('2026-2738-1031500-100002')"))
        yield connection


def _run(migration, monkeypatch, connection, step):
    monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
    getattr(migration, step)()


def _columns(connection):
    return {c['name'] for c in sa.inspect(connection).get_columns('site_settings')}


def test_upgrade_drops_only_the_counters(migration, monkeypatch, conn):
    _run(migration, monkeypatch, conn, 'upgrade')

    assert _columns(conn) == {'id', 'bpr_provider_number'}
    assert conn.execute(sa.text(
        'SELECT bpr_provider_number FROM site_settings')).scalar() == '2738'


def test_downgrade_restores_counters_above_every_issued_number(migration,
                                                               monkeypatch, conn):
    _run(migration, monkeypatch, conn, 'upgrade')
    _run(migration, monkeypatch, conn, 'downgrade')

    row = conn.execute(sa.text(
        'SELECT bpr_participant_counter, bpr_lecturer_counter FROM site_settings'
    )).one()
    assert tuple(row) == (6, 2)


@pytest.mark.parametrize('numbers, expected', [
    (['2026-2738-1028974-000004', '2026-27-974-9'], 9),
    (['IPRM-2026-000001', None, ''], 0),
    ([], 0),
])
def test_max_segment(migration, numbers, expected):
    assert migration.max_segment(numbers) == expected


def test_offset_matches_the_model(migration):
    from app.models.lecturer_certificate import LECTURER_NUMBER_OFFSET
    assert migration.LECTURER_NUMBER_OFFSET == LECTURER_NUMBER_OFFSET
