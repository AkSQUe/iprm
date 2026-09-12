"""Оборотність міграції ``bpr_points_split_20260909`` на справжньому Postgres.

Сусідній ``test_migration_bpr_points_split.py`` перевіряє ПЕРЕНЕСЕННЯ ДАНИХ:
він виконує згенерований SQL на тимчасових таблицях SQLite. Цього замало для
самої міграції: вона дропає колонку, міняє тип на ``NUMERIC`` і знімає та
ставить CHECK-обмеження, а SQLite цього не вміє. Тобто ``upgrade()`` і
``downgrade()`` як функції не виконувались НІКОДИ -- ані в тестах, ані
локально: dev-база проєкту спільна на кілька ворктрі, і в момент випуску вона
була проштампована ревізією з чужої гілки, через що ``flask db`` там не
запускався взагалі. Міграція поїхала в прод 10.09.2026 з перевіреним лише
перенесенням даних.

Цей файл закриває саме ту прогалину і робить це повторюваним.

ЧОМУ ЦИКЛ, А НЕ ОДНЕ ``upgrade()``. Перевіряється ``upgrade -> downgrade ->
upgrade``, бо одноразове застосування не ловить забуті об'єкти схеми.
Конкретний випадок звідси: ``upgrade`` дропає ``ck_*_cpd_points_non_negative``,
і якби ``downgrade`` не відтворив їх, ПОВТОРНИЙ ``upgrade`` спіткнувся б об
``DROP CONSTRAINT`` неіснуючого обмеження. Рецензент оцінив це як косметику,
контролер підвищив до блокера -- саме тому, що доводиться це лише циклом.

ТИМЧАСОВА СХЕМА, А НЕ ТИМЧАСОВА БАЗА. Роль застосунку не має ``CREATEDB``,
тож ізоляція будується схемою ``bpr_points_rev_<pid>`` усередині dev-бази.
``alembic_version`` ми не чіпаємо: викликаються самі функції міграції на
НАШИХ таблицях у НАШІЙ схемі, тож стан чужих ворктрі лишається недоторканим.

Без ``DATABASE_URL_DEV`` (або без доступу до сервера) тест пропускається, а
не падає: у CI без бази це відсутність умов, а не регресія.
"""
import importlib.util
import os
import pathlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = (pathlib.Path(__file__).resolve().parents[2] / 'migrations'
             / 'versions' / 'bpr_points_split_20260909_add_format_columns.py')

SCHEMA = 'bpr_points_rev_%d' % os.getpid()

#: Мінімальні копії таблиць СТАНОМ ДО міграції -- лише ті колонки, яких вона
#: торкається, плюс ключі, потрібні для бекфілу формату участі з тарифу.
BEFORE = """
CREATE TABLE courses (
    id BIGSERIAL PRIMARY KEY,
    slug VARCHAR(200) NOT NULL,
    cpd_points INTEGER,
    bpr_lecturer_points INTEGER,
    CONSTRAINT ck_courses_cpd_points_non_negative
        CHECK (cpd_points >= 0 OR cpd_points IS NULL)
);
CREATE TABLE course_instances (
    id BIGSERIAL PRIMARY KEY,
    course_id BIGINT NOT NULL,
    event_format VARCHAR(20),
    cpd_points INTEGER,
    CONSTRAINT ck_course_instances_cpd_points_non_negative
        CHECK (cpd_points >= 0 OR cpd_points IS NULL)
);
CREATE TABLE instance_tariffs (
    id BIGSERIAL PRIMARY KEY,
    instance_id BIGINT NOT NULL,
    event_format VARCHAR(20)
);
CREATE TABLE event_registrations (
    id BIGSERIAL PRIMARY KEY,
    instance_id BIGINT,
    tariff_id BIGINT,
    cpd_points_awarded INTEGER
);
CREATE TABLE certificates (
    id BIGSERIAL PRIMARY KEY,
    cpd_points INTEGER
);
CREATE TABLE lecturer_certificates (
    id BIGSERIAL PRIMARY KEY,
    cpd_points INTEGER
);
CREATE TABLE online_courses (
    id BIGSERIAL PRIMARY KEY,
    cpd_points INTEGER
);
"""


def _load():
    spec = importlib.util.spec_from_file_location('m_bpr_points_rev', MIGRATION)
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
    -- це команда, яка в разі помилки влучає у справжні курси.
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
            "INSERT INTO courses (id, slug, cpd_points, bpr_lecturer_points) "
            "VALUES (1, 'kurs', 12, 16), (2, 'bez-baliv', NULL, NULL)"))
        connection.execute(sa.text(
            "INSERT INTO course_instances (id, course_id, event_format, cpd_points) "
            "VALUES (1, 1, 'hybrid', 9), (2, 1, 'online', NULL)"))
        connection.execute(sa.text(
            "INSERT INTO instance_tariffs (id, instance_id, event_format) "
            "VALUES (1, 1, 'online'), (2, 1, NULL)"))
        connection.execute(sa.text(
            'INSERT INTO event_registrations '
            '(id, instance_id, tariff_id, cpd_points_awarded) '
            'VALUES (1, 1, 1, 9), (2, 1, 2, NULL), (3, 1, NULL, NULL)'))
        for table in ('certificates', 'lecturer_certificates', 'online_courses'):
            connection.execute(sa.text(
                'INSERT INTO %s (id, cpd_points) VALUES (1, 10)' % table))
    return engine


def _run(connection, direction):
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(_load(), direction)()


def _columns(connection, table):
    return connection.execute(sa.text(
        'SELECT column_name FROM information_schema.columns '
        "WHERE table_schema = '%s' AND table_name = '%s'" % (SCHEMA, table)
    )).scalars().all()


class TestUpgrade:

    def test_points_land_in_both_columns_and_old_one_goes(self, prepared):
        """Головне, заради чого міграція існує: наявні бали не зникають у
        мить, коли стара колонка йде."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            rows = connection.execute(sa.text(
                'SELECT cpd_points_online, cpd_points_offline '
                'FROM course_instances ORDER BY id')).all()
            names = _columns(connection, 'course_instances')
        assert (float(rows[0][0]), float(rows[0][1])) == (9.0, 9.0)
        assert rows[1] == (None, None)
        assert 'cpd_points' not in names

    def test_fractional_points_fit_after_upgrade(self, prepared):
        """Заради чого міняли тип: Integer обрізав би 7,5 до 7."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            connection.execute(sa.text(
                'UPDATE course_instances SET cpd_points_online = 7.5 WHERE id = 1'))
            connection.execute(sa.text(
                'UPDATE courses SET bpr_lecturer_points = 16.5 WHERE id = 1'))
            connection.execute(sa.text(
                'UPDATE event_registrations SET cpd_points_awarded = 4.5 WHERE id = 1'))
            online = connection.execute(sa.text(
                'SELECT cpd_points_online FROM course_instances WHERE id = 1')).scalar()
            lecturer = connection.execute(sa.text(
                'SELECT bpr_lecturer_points FROM courses WHERE id = 1')).scalar()
            awarded = connection.execute(sa.text(
                'SELECT cpd_points_awarded FROM event_registrations '
                'WHERE id = 1')).scalar()
        assert (float(online), float(lecturer), float(awarded)) == (7.5, 16.5, 4.5)

    def test_participation_format_backfilled_only_from_a_real_tariff(self, prepared):
        """Формат бере з тарифу; NULL у тарифі й реєстрація без тарифу
        лишаються порожніми, бо далі спрацює `effective_participation_format`."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            rows = connection.execute(sa.text(
                'SELECT id, participation_format FROM event_registrations '
                'ORDER BY id')).all()
        assert [r[1] for r in rows] == ['online', None, None]

    def test_new_check_constraints_actually_bite(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
        with pytest.raises(sa.exc.DBAPIError):
            with prepared.begin() as connection:
                connection.execute(sa.text(
                    'UPDATE course_instances SET cpd_points_online = -1'))
        with pytest.raises(sa.exc.DBAPIError):
            with prepared.begin() as connection:
                connection.execute(sa.text(
                    "UPDATE event_registrations SET participation_format = 'гібрид'"))


class TestReversibility:

    def test_downgrade_collapses_to_the_offline_value(self, prepared):
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            connection.execute(sa.text(
                'UPDATE course_instances SET cpd_points_online = 4, '
                'cpd_points_offline = 9 WHERE id = 1'))
            _run(connection, 'downgrade')
            value = connection.execute(sa.text(
                'SELECT cpd_points FROM course_instances WHERE id = 1')).scalar()
            names = _columns(connection, 'course_instances')
        assert value == 9
        assert 'cpd_points_online' not in names
        assert 'cpd_points_offline' not in names

    def test_downgrade_restores_the_old_check_constraint(self, prepared):
        """Саме через це повторний upgrade і має шанс пройти: обмеження, яке
        він дропає, мусить існувати."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            _run(connection, 'downgrade')
        with pytest.raises(sa.exc.DBAPIError):
            with prepared.begin() as connection:
                connection.execute(sa.text(
                    'UPDATE courses SET cpd_points = -1 WHERE id = 1'))

    def test_full_cycle_survives_a_second_upgrade(self, prepared):
        """Одноразове застосування не ловить забуті об'єкти схеми -- цикл ловить."""
        with prepared.begin() as connection:
            _run(connection, 'upgrade')
            _run(connection, 'downgrade')
            _run(connection, 'upgrade')
            names = _columns(connection, 'courses')
        assert 'cpd_points_online' in names
        assert 'cpd_points_offline' in names
        assert 'cpd_points' not in names
