import sqlite3
import threading

import pytest
from flask_sqlalchemy.session import Session as _FlaskSQLAlchemySession
from sqlalchemy import event as _sa_event
from sqlalchemy.engine import Engine as _SAEngine
from sqlalchemy.orm import Session as _SAOrmSession

from app import create_app
from app.extensions import db as _db


# ---------------------------------------------------------------------------
# SQLite: справжні транзакції замість автокоміту
# ---------------------------------------------------------------------------
# Драйвер ``pysqlite`` сам вирішує, коли починати транзакцію, і робить це лише
# перед DML. ``SAVEPOINT`` / ``RELEASE SAVEPOINT`` для нього не DML -- збережена
# точка створюється поза транзакцією, а ``RELEASE`` стає справжнім ``COMMIT``.
# Без цих двох слухачів зовнішня транзакція нижче не має чого відкочувати.
#
# Рецепт із документації SQLAlchemy (драйвер pysqlite, розділ "Serializable
# isolation / Savepoints / Transactional DDL"): вимкнути автоматичний BEGIN
# драйвера і видавати його самим.
@_sa_event.listens_for(_SAEngine, 'connect')
def _sqlite_disable_driver_autobegin(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.isolation_level = None


@_sa_event.listens_for(_SAEngine, 'begin')
def _sqlite_emit_explicit_begin(conn):
    if conn.engine.dialect.name != 'sqlite':
        return
    # In-memory SQLite ділить ОДНЕ з'єднання драйвера між кількома
    # Connection-об'єктами SQLAlchemy (SingletonThreadPool). Другий BEGIN на
    # тому ж з'єднанні -- це "cannot start a transaction within a
    # transaction", тому питаємо драйвер, а не припускаємо.
    if not conn.connection.dbapi_connection.in_transaction:
        conn.exec_driver_sql('BEGIN')


@pytest.fixture(scope='session')
def app():
    """Flask-додаток для тестування. Ролі й права сідяться один раз на сесію:
    без них жоден адмін-маршрут не відкрити."""
    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        from app.rbac import service as rbac_service
        rbac_service.sync()
        _db.session.commit()
        yield app
        _db.drop_all()


@pytest.fixture(autouse=True)
def db_session(app):
    """Чиста сесія БД для кожного тесту (з відкатом).

    Фікстура довго НЕ ізолювала нічого, і мовчки. Вона будувала словник
    ``options = dict(bind=connection, join_transaction_block=True)`` -- і
    ніде його не застосовувала. ``_db.session`` лишалась прив'язаною до
    двигуна, тобто відкривала власне з'єднання: ``transaction.rollback()``
    відкочував транзакцію, в яку ніхто нічого не писав, а кожен
    ``session.commit()`` усередині тесту жив до кінця прогону.

    Прив'язати сесію ``configure(bind=...)`` НЕДОСТАТНЬО:
    ``flask_sqlalchemy.session.Session.get_bind()`` перевизначено і воно
    ніколи не читає ``self.bind`` -- обирає двигун за bind_key метаданих і
    повертає ``db.engines[None]``. Тому підміна робиться там, де bind справді
    читають.

    Тільки для потоку, який виконує тест: фоновим потокам застосунку лишається
    звичайний двигун -- одне з'єднання SQLite на два потоки дало б помилку
    замість ізоляції, і незакомічену транзакцію тесту вони бачити не мають.
    """
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin()
        # Збережена точка НАВКОЛО всього тесту -- не косметика.
        #
        # Тестова БД -- ``sqlite:///:memory:``, а це один-єдиний з'єднувач
        # драйвера на потік (``SingletonThreadPool``): скільки б Connection не
        # створив SQLAlchemy, за ними стоїть та сама база і та сама транзакція.
        # Код застосунку відкриває власні короткоживучі сесії
        # (``Session(db.engine)`` у ``webhook_queue.enqueue``, викликається з
        # ``after_commit``), і ``ROLLBACK`` на виході з такої сесії зносив
        # зовнішню транзакцію тесту разом із усім, що тест уже записав.
        # Виміряно: після ``db.session.commit()`` рядок зникав, а в журналі SQL
        # між COMMIT-ом і наступним запитом стояв чужий ROLLBACK.
        #
        # Поки ми всередині збереженої точки, ``conn.in_nested_transaction()``
        # істинне, і така сесія за замовчуванням (``conditional_savepoint``)
        # бере СВОЮ збережену точку замість зовнішньої транзакції. Її commit і
        # rollback лишаються всередині тесту.
        connection.begin_nested()

        test_thread = threading.get_ident()
        original_get_bind = _FlaskSQLAlchemySession.get_bind
        original_plain_get_bind = _SAOrmSession.get_bind

        def _get_bind_for_test(self, *args, **kwargs):
            if threading.get_ident() == test_thread:
                return connection
            return original_get_bind(self, *args, **kwargs)

        def _plain_get_bind_for_test(self, *args, **kwargs):
            if threading.get_ident() == test_thread:
                self.join_transaction_mode = 'rollback_only'
                return connection
            return original_plain_get_bind(self, *args, **kwargs)

        _FlaskSQLAlchemySession.get_bind = _get_bind_for_test
        _SAOrmSession.get_bind = _plain_get_bind_for_test

        # ``create_savepoint``: commit() усередині тесту стає SAVEPOINT-ом.
        # Код, який комітить (а такого в сервісах багато), працює як звичайно,
        # але назовні зовнішньої транзакції нічого не потрапляє.
        _db.session.remove()
        _db.session.configure(bind=connection,
                              join_transaction_mode='create_savepoint')

        try:
            yield _db.session
        finally:
            _db.session.remove()
            _FlaskSQLAlchemySession.get_bind = original_get_bind
            _SAOrmSession.get_bind = original_plain_get_bind
            transaction.rollback()
            connection.close()
            _db.session.configure(bind=_db.engine)


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def liqpay_keys(app):
    """Налаштований LiqPay: без ключів маршрути не будують платіжну форму.

    Значення відновлюються після тесту. SiteSettings -- singleton, і хоча
    відкат тестової транзакції прибирає зміну сам, покладатись на це в
    тесті, який щось комітить, було б тонким припущенням.
    """
    from app.models.site_settings import SiteSettings

    settings = SiteSettings.get()
    before = (settings.liqpay_public_key, settings.liqpay_private_key,
              settings.liqpay_sandbox)
    settings.liqpay_public_key = 'sandbox_i000000000'
    settings.liqpay_private_key = 'sandbox_secret'
    settings.liqpay_sandbox = True
    _db.session.flush()

    yield settings

    (settings.liqpay_public_key, settings.liqpay_private_key,
     settings.liqpay_sandbox) = before
    _db.session.flush()
