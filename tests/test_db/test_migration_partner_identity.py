"""Оборотність міграції ``partner_identity_20260912`` на справжньому Postgres.

Міграція знімає й ставить CHECK ``ck_auth_identities_provider``, а на
``downgrade`` ще й видаляє рядки, які у вужчий CHECK не влізуть. SQLite
жодного з цих кроків не вміє, тож у звичайному прогоні тестів ці функції не
виконуються НІКОЛИ -- перевірити їх можна лише тут.

Цикл ``upgrade -> downgrade -> upgrade``, а не одне застосування: якби
``downgrade`` не відтворив обмеження, повторний ``upgrade`` спіткнувся б об
``DROP CONSTRAINT`` неіснуючого. Одноразовий прогін такого не ловить.

Ізоляція -- тимчасова СХЕМА в dev-базі (роль застосунку не має ``CREATEDB``),
``alembic_version`` не чіпаємо: викликаються самі функції міграції на наших
таблицях. Без ``DATABASE_URL_DEV`` чи без доступу до сервера тест
пропускається: це відсутність умов, а не регресія.
"""
import importlib.util
import os
import pathlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = (pathlib.Path(__file__).resolve().parents[2] / 'migrations'
             / 'versions' / 'partner_identity_20260912.py')

SCHEMA = 'partner_identity_rev_%d' % os.getpid()

#: Копія ``auth_identities`` СТАНОМ ДО міграції -- лише те, чого вона торкається.
BEFORE = """
CREATE TABLE auth_identities (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    provider VARCHAR(20) NOT NULL,
    provider_sub VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    password_hash VARCHAR(255),
    CONSTRAINT ck_auth_identities_provider
        CHECK (provider IN ('password', 'google', 'apple'))
);
"""


def _load():
    spec = importlib.util.spec_from_file_location('m_partner_identity', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dev_url():
    raw = os.environ.get('DATABASE_URL_DEV')
    if not raw:
        env = pathlib.Path(__file__).resolve().parents[2] / '.env'
        if env.exists():
            for line in env.read_text(encoding='utf-8').splitlines():
                if line.startswith('DATABASE_URL_DEV='):
                    raw = line.split('=', 1)[1].strip()
                    break
    return raw


@pytest.fixture(scope='module')
def engine():
    raw = _dev_url()
    if not raw:
        pytest.skip('DATABASE_URL_DEV не заданий -- немає де створити схему')

    target = sa.create_engine(raw, pool_pre_ping=True)

    @sa.event.listens_for(target, 'connect')
    def _set_search_path(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute('SET search_path TO %s' % SCHEMA)
        cursor.close()

    try:
        with target.begin() as connection:
            connection.execute(sa.text('CREATE SCHEMA IF NOT EXISTS %s' % SCHEMA))
    except Exception as exc:                       # noqa: BLE001
        sa.event.remove(target, 'connect', _set_search_path)
        target.dispose()
        pytest.skip('Сервер dev-бази недосяжний: %s' % exc)

    try:
        yield target
    finally:
        sa.event.remove(target, 'connect', _set_search_path)
        with target.begin() as connection:
            connection.execute(sa.text('DROP SCHEMA IF EXISTS %s CASCADE' % SCHEMA))
        target.dispose()


@pytest.fixture()
def prepared(engine):
    """Схема «до міграції» з рядком, який має пережити обидва напрямки."""
    with engine.begin() as connection:
        here = connection.execute(sa.text('SELECT current_schema()')).scalar()
        assert here == SCHEMA, (
            'DDL пішов би повз тимчасову схему: current_schema()=%r' % here)
        connection.execute(sa.text('DROP SCHEMA %s CASCADE' % SCHEMA))
        connection.execute(sa.text('CREATE SCHEMA %s' % SCHEMA))
        for statement in BEFORE.strip().split(';'):
            if statement.strip():
                connection.execute(sa.text(statement))
        connection.execute(sa.text(
            "INSERT INTO auth_identities "
            "(id, user_id, provider, provider_sub, email, password_hash) "
            "VALUES (1, 1, 'password', '1', 'ivan@example.com', 'hash')"))
    return engine


def _run(connection, direction):
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(_load(), direction)()


def _insert_partner(connection, row_id=2, user_id=2):
    connection.execute(sa.text(
        "INSERT INTO auth_identities "
        "(id, user_id, provider, provider_sub, email) "
        "VALUES (:i, :u, 'partner', :sub, 'lunev.a@mm-medic.com')"),
        {'i': row_id, 'u': user_id, 'sub': 'mm-medic:%d' % row_id})


def _assert_partner_rejected(engine, row_id, user_id):
    """Вставка партнерського рядка має впертись у CHECK.

    Власна транзакція на спробу: порушення обмеження абортує транзакцію
    цілком, і будь-який наступний запит у тому ж блоці впав би вже з
    "current transaction is aborted", маскуючи справжню причину.

    Ловимо DBAPIError, а не IntegrityError: pg8000 мапить check_violation
    (SQLSTATE 23514) у ProgrammingError, тож перевіряємо саме обмеження.
    """
    with pytest.raises(sa.exc.DBAPIError) as excinfo:
        with engine.begin() as connection:
            _insert_partner(connection, row_id, user_id)
    assert 'ck_auth_identities_provider' in str(excinfo.value)


class TestUpgrade:

    def test_partner_provider_rejected_before(self, prepared):
        """Доказ, що міграція потрібна: до неї CHECK партнера не пускає."""
        _assert_partner_rejected(prepared, row_id=2, user_id=2)

    def test_partner_provider_allowed_after(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            _insert_partner(connection)
            count = connection.execute(sa.text(
                "SELECT count(*) FROM auth_identities WHERE provider = 'partner'"
            )).scalar()
        assert count == 1


class TestDowngrade:

    def test_partner_rows_go_and_check_narrows(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            _insert_partner(connection)
            _run(connection, 'downgrade')
            remaining = connection.execute(sa.text(
                'SELECT provider FROM auth_identities ORDER BY id')).scalars().all()
        assert remaining == ['password'], 'акаунти з паролем чіпати не можна'
        _assert_partner_rejected(prepared, row_id=3, user_id=3)

    def test_upgrade_downgrade_upgrade_cycle(self, prepared):
        """Забуте в downgrade обмеження ловиться лише повторним upgrade."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            _run(connection, 'downgrade')
            _run(connection, 'upgrade')
            _insert_partner(connection, row_id=4, user_id=4)
            count = connection.execute(sa.text(
                "SELECT count(*) FROM auth_identities WHERE provider = 'partner'"
            )).scalar()
        assert count == 1
