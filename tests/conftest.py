import pytest
from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope='session')
def app():
    """Flask-додаток для тестування."""
    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


@pytest.fixture(autouse=True)
def db_session(app):
    """Чиста сесія БД для кожного тесту (з відкатом)."""
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin()
        options = dict(bind=connection, join_transaction_block=True)
        session = _db.session

        yield session

        session.close()
        transaction.rollback()
        connection.close()


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
