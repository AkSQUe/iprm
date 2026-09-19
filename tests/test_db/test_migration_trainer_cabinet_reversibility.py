"""Оборотність міграції ``trainer_cabinet_20260919`` на справжньому Postgres.

Міграція торкається чотирьох таблиць: додає ``trainers.user_id`` з
унікальністю й FK на ``users``, створює ``trainer_profiles`` (FK на
``trainers`` і ``media_files``) та ``trainer_course_proposals`` (CHECK
статусу, два індекси) і п'ять колонок у ``site_settings``. На SQLite тестів
схему будує ``db.create_all()``, тож сама міграція там не виконується --
ні імена обмежень, ні порядок DROP у ``downgrade`` ніхто не перевіряв.

ЩО ДОВОДИТЬСЯ, КРІМ DDL. Бекфілу немає: наявні тренери лишаються без
акаунта (``user_id`` NULL), а наявний рядок ``site_settings`` отримує
порожні рядки з ``server_default`` -- NOT NULL колонки без них упали б на
таблиці з даними. Це видно лише на непорожніх таблицях.

ЧОМУ ЦИКЛ. ``upgrade -> downgrade -> upgrade``: одне застосування не ловить
забутих у ``downgrade`` об'єктів (індекс, обмеження), об які спіткнувся б
повторний прогін.

ТИМЧАСОВА СХЕМА, А НЕ БАЗА: роль застосунку не має ``CREATEDB``. Викликаються
самі функції міграції на НАШИХ таблицях у НАШІЙ схемі, ``alembic_version``
не чіпаємо. Без ``DATABASE_URL_DEV`` (або без доступу до сервера) тест
пропускається: у CI без бази це відсутність умов, а не регресія.
"""
import importlib.util
import os
import pathlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = (pathlib.Path(__file__).resolve().parents[2] / 'migrations'
             / 'versions' / 'trainer_cabinet_20260919.py')

SCHEMA = 'trainer_cabinet_rev_%d' % os.getpid()

#: Мінімальні таблиці СТАНОМ ДО міграції -- лише те, на що вона посилається.
BEFORE = """
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL
);
CREATE TABLE trainers (
    id BIGSERIAL PRIMARY KEY,
    full_name VARCHAR(200) NOT NULL
);
CREATE TABLE media_files (
    id BIGSERIAL PRIMARY KEY
);
CREATE TABLE site_settings (
    id INTEGER PRIMARY KEY,
    email VARCHAR(255)
);
"""

NEW_TABLES = ('trainer_profiles', 'trainer_course_proposals')
NEW_SETTINGS = ('trainer_faq_html', 'trainer_contract_email', 'trainer_contract_pdf',
                'trainer_contract_filename', 'trainer_contract_uploaded_at')


def _load():
    spec = importlib.util.spec_from_file_location('m_trainer_cabinet_rev', MIGRATION)
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
    """Схема «до міграції» з непорожніми таблицями.

    Чиститься СХЕМА, а не таблиці: ``DROP TABLE`` без гарантії ``search_path``
    -- команда, яка в разі помилки влучає у справжніх тренерів.
    """
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
            "INSERT INTO users (id, email) VALUES (1, 'a@test.com'), (2, 'b@test.com')"))
        connection.execute(sa.text(
            "INSERT INTO trainers (id, full_name) VALUES (1, 'Перший'), (2, 'Другий')"))
        connection.execute(sa.text(
            "INSERT INTO site_settings (id, email) VALUES (1, 'site@test.com')"))
    return engine


def _run(connection, direction):
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(_load(), direction)()


def _tables(connection):
    return set(connection.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = '%s'" % SCHEMA)).scalars())


def _columns(connection, table):
    return set(connection.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = '%s' AND table_name = '%s'" % (SCHEMA, table))).scalars())


def _constraints(connection, table):
    return set(connection.execute(sa.text(
        "SELECT constraint_name FROM information_schema.table_constraints "
        "WHERE table_schema = '%s' AND table_name = '%s'" % (SCHEMA, table))).scalars())


class TestUpgrade:

    def test_schema_objects_appear(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            tables = _tables(connection)
            trainer_cols = _columns(connection, 'trainers')
            trainer_constraints = _constraints(connection, 'trainers')
            settings_cols = _columns(connection, 'site_settings')
            proposal_constraints = _constraints(connection, 'trainer_course_proposals')
        assert set(NEW_TABLES) <= tables
        assert 'user_id' in trainer_cols
        assert {'uq_trainers_user_id', 'fk_trainers_user_id_users'} <= trainer_constraints
        assert set(NEW_SETTINGS) <= settings_cols
        assert 'ck_trainer_course_proposals_status' in proposal_constraints

    def test_existing_rows_get_no_backfill(self, prepared):
        """Тренери лишаються без акаунта; наявний рядок налаштувань отримує
        порожні рядки (server_default), а не падає на NOT NULL."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            user_ids = connection.execute(sa.text(
                'SELECT user_id FROM trainers ORDER BY id')).scalars().all()
            row = connection.execute(sa.text(
                'SELECT trainer_faq_html, trainer_contract_email, '
                'trainer_contract_filename, trainer_contract_pdf FROM site_settings'
            )).one()
        assert user_ids == [None, None]
        assert tuple(row) == ('', '', '', None)

    def test_one_account_per_trainer(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            connection.execute(sa.text('UPDATE trainers SET user_id = 1 WHERE id = 1'))
        # pg8000 віддає порушення обмежень то IntegrityError, то
        # ProgrammingError -- ловимо спільний DBAPIError і звіряємо ім'я.
        with pytest.raises(sa.exc.DBAPIError, match='uq_trainers_user_id'):
            with prepared.begin() as connection:
                connection.execute(sa.text('UPDATE trainers SET user_id = 1 WHERE id = 2'))

    def test_status_check_rejects_unknown(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            connection.execute(sa.text(
                "INSERT INTO trainer_course_proposals (trainer_id, title, theses) "
                "VALUES (1, 'КОС', '[]')"))
            status = connection.execute(sa.text(
                'SELECT status FROM trainer_course_proposals')).scalar()
        assert status == 'draft'
        with pytest.raises(sa.exc.DBAPIError, match='ck_trainer_course_proposals_status'):
            with prepared.begin() as connection:
                connection.execute(sa.text(
                    "INSERT INTO trainer_course_proposals (trainer_id, title, theses, status) "
                    "VALUES (1, 'КОС', '[]', 'rejected')"))


class TestDowngrade:

    def test_everything_goes_away_with_data(self, prepared):
        """Відкат із заповненими анкетою й пропозицією не падає на FK --
        таблиці падають раніше за колонку, на яку вони посилаються."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            connection.execute(sa.text('UPDATE trainers SET user_id = 1 WHERE id = 1'))
            connection.execute(sa.text(
                "INSERT INTO trainer_profiles (trainer_id, full_name) VALUES (1, 'Перший')"))
            connection.execute(sa.text(
                "INSERT INTO trainer_course_proposals (trainer_id, title, theses) "
                "VALUES (1, 'КОС', '[]')"))
            _run(connection, 'downgrade')
            tables = _tables(connection)
            trainer_cols = _columns(connection, 'trainers')
            settings_cols = _columns(connection, 'site_settings')
            trainers = connection.execute(sa.text(
                'SELECT id FROM trainers ORDER BY id')).scalars().all()
        assert not (set(NEW_TABLES) & tables)
        assert 'user_id' not in trainer_cols
        assert not (set(NEW_SETTINGS) & settings_cols)
        assert trainers == [1, 2]


class TestCycle:

    def test_upgrade_downgrade_upgrade(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            _run(connection, 'downgrade')
            _run(connection, 'upgrade')
            tables = _tables(connection)
            trainer_constraints = _constraints(connection, 'trainers')
        assert set(NEW_TABLES) <= tables
        assert {'uq_trainers_user_id', 'fk_trainers_user_id_users'} <= trainer_constraints
