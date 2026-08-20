"""DevelopmentConfig мусить мати власну базу.

Доти в ІПРМ був один DATABASE_URL, і він вів на прод: будь-яка міграція
вперше виконувалась одразу в бойовій базі. Тест фіксує саме те, що
розділення існує, а не те, що воно налаштоване на конкретній машині.
"""
import importlib


def _reload_config(monkeypatch, env):
    for key in ('DATABASE_URL', 'DATABASE_URL_DEV'):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config as config_module
    return importlib.reload(config_module)


def test_development_prefers_dev_database_url(monkeypatch):
    cfg = _reload_config(monkeypatch, {
        'DATABASE_URL': 'postgresql+pg8000://prod/prod_db',
        'DATABASE_URL_DEV': 'postgresql+pg8000://dev/dev_db',
    })
    assert cfg.DevelopmentConfig.SQLALCHEMY_DATABASE_URI == 'postgresql+pg8000://dev/dev_db'


def test_development_falls_back_to_database_url(monkeypatch):
    cfg = _reload_config(monkeypatch, {
        'DATABASE_URL': 'postgresql+pg8000://prod/prod_db',
    })
    assert cfg.DevelopmentConfig.SQLALCHEMY_DATABASE_URI == 'postgresql+pg8000://prod/prod_db'


def test_production_ignores_dev_database_url(monkeypatch):
    cfg = _reload_config(monkeypatch, {
        'DATABASE_URL': 'postgresql+pg8000://prod/prod_db',
        'DATABASE_URL_DEV': 'postgresql+pg8000://dev/dev_db',
    })
    assert cfg.ProductionConfig.SQLALCHEMY_DATABASE_URI == 'postgresql+pg8000://prod/prod_db'
