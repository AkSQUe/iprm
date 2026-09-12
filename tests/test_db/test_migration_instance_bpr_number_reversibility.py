"""Оборотність міграції ``instance_bpr_number_20260912`` на справжньому Postgres.

Міграція проста -- один nullable ``add_column`` -- але виконана не була жодного
разу: dev-база проєкту спільна на кілька ворктрі й на момент випуску стояла
проштампована ревізією з чужої гілки, через що ``flask db`` там не запускався
взагалі. Рівно так у прод 10.09.2026 поїхала ``bpr_points_split_20260909``
(див. сусідній ``test_migration_bpr_points_split_reversibility.py``). "Проста"
і "перевірена" -- різні властивості, і ця прогалина закривається тут.

ЩО САМЕ ДОВОДИТЬСЯ, КРІМ DDL. Друге твердження міграції -- що бекфілу НЕМАЄ:
наявні дати лишаються з NULL, тобто після деплою поводяться рівно як до нього
(``effective_bpr_event_number`` віддає курсовий номер). Якби колонка
створювалась із DEFAULT або зі скопійованим курсовим номером, різниця між
"номер успадковано" і "номер свідомо виписано на цю дату" зникла б у даних
назавжди. Перевіряється це тільки на живій таблиці з рядками.

ЧОМУ ЦИКЛ, А НЕ ОДНЕ ``upgrade()``. ``upgrade -> downgrade -> upgrade``: одне
застосування не ловить забуті об'єкти схеми, через які ПОВТОРНИЙ прогін
спіткнувся б об уже наявну колонку.

ТИМЧАСОВА СХЕМА, А НЕ ТИМЧАСОВА БАЗА. Роль застосунку не має ``CREATEDB``, тож
ізоляція будується схемою всередині dev-бази. ``alembic_version`` не чіпаємо:
викликаються самі функції міграції на НАШИХ таблицях у НАШІЙ схемі, тож стан
чужих ворктрі лишається недоторканим.

Без ``DATABASE_URL_DEV`` (або без доступу до сервера) тест пропускається, а не
падає: у CI без бази це відсутність умов, а не регресія.
"""
import importlib.util
import os
import pathlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = (pathlib.Path(__file__).resolve().parents[2] / 'migrations'
             / 'versions' / 'instance_bpr_number_20260912.py')

SCHEMA = 'bpr_event_num_rev_%d' % os.getpid()

#: Мінімальна копія таблиці СТАНОМ ДО міграції -- лише те, чого вона торкається.
BEFORE = """
CREATE TABLE course_instances (
    id BIGSERIAL PRIMARY KEY,
    course_id BIGINT NOT NULL,
    event_format VARCHAR(20)
);
"""


def _load():
    spec = importlib.util.spec_from_file_location('m_bpr_event_num_rev', MIGRATION)
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
    """Схема «до міграції» з непорожньою таблицею.

    Чиститься СХЕМА, а не таблиця: ``DROP TABLE`` без гарантії ``search_path``
    -- це команда, яка в разі помилки влучає у справжні проведення.
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
            "INSERT INTO course_instances (id, course_id, event_format) "
            "VALUES (1, 1, 'offline'), (2, 1, 'online')"))
    return engine


def _run(connection, direction):
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(_load(), direction)()


def _column(connection, name='bpr_event_number'):
    return connection.execute(sa.text(
        'SELECT data_type, character_maximum_length, is_nullable, column_default '
        'FROM information_schema.columns '
        "WHERE table_schema = '%s' AND table_name = 'course_instances' "
        "AND column_name = '%s'" % (SCHEMA, name)
    )).first()


class TestUpgrade:

    def test_column_appears_nullable_and_twenty_long(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            column = _column(connection)
        assert column is not None, 'колонки немає -- upgrade не спрацював'
        data_type, length, nullable, default = column
        assert (data_type, length, nullable) == ('character varying', 20, 'YES')
        assert default is None, (
            'DEFAULT перетворив би "номер успадковано" на "номер виписано"')

    def test_existing_dates_stay_empty(self, prepared):
        """Бекфілу немає навмисне: наявні дати мусять лишитись на курсовому
        номері, інакше відрізнити успадкований номер від свідомо виписаного
        стане неможливо."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            values = connection.execute(sa.text(
                'SELECT bpr_event_number FROM course_instances ORDER BY id'
            )).scalars().all()
        assert values == [None, None]

    def test_number_written_after_upgrade_survives(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            connection.execute(sa.text(
                "UPDATE course_instances SET bpr_event_number = '1031500' "
                'WHERE id = 1'))
            values = connection.execute(sa.text(
                'SELECT bpr_event_number FROM course_instances ORDER BY id'
            )).scalars().all()
        assert values == ['1031500', None]


class TestDowngrade:

    def test_column_goes_away(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            _run(connection, 'downgrade')
            column = _column(connection)
        assert column is None

    def test_downgrade_survives_filled_numbers(self, prepared):
        """Відкат із заповненими номерами не падає -- він їх втрачає, і це
        свідомо: після відкату сертифікати знову беруть номер курсу."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            connection.execute(sa.text(
                "UPDATE course_instances SET bpr_event_number = '1031500'"))
            _run(connection, 'downgrade')
            rows = connection.execute(sa.text(
                'SELECT id FROM course_instances ORDER BY id')).scalars().all()
        assert rows == [1, 2]


class TestCycle:

    def test_upgrade_downgrade_upgrade(self, prepared):
        """Одноразовий прогін не ловить забутих об'єктів схеми: повторний
        upgrade спіткнувся б об колонку, яку downgrade не прибрав."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            _run(connection, 'downgrade')
            _run(connection, 'upgrade')
            column = _column(connection)
            values = connection.execute(sa.text(
                'SELECT bpr_event_number FROM course_instances ORDER BY id'
            )).scalars().all()
        assert column is not None
        assert values == [None, None]
