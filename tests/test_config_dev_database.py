"""DevelopmentConfig мусить мати власну базу.

Доти в ІПРМ був один DATABASE_URL, і він вів на прод: будь-яка міграція
вперше виконувалась одразу в бойовій базі. Тест фіксує саме те, що
розділення існує, а не те, що воно налаштоване на конкретній машині.
"""
import importlib

import dotenv


def _reload_config(monkeypatch, env):
    for key in ('DATABASE_URL', 'DATABASE_URL_DEV'):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config as config_module
    # config.py calls load_dotenv() at module level. A real reload re-runs
    # `from dotenv import load_dotenv` too, so patching config_module's own
    # attribute does not stick -- reload rebinds it from the dotenv package
    # again before the call. Patching it on the SOURCE (dotenv.load_dotenv)
    # is what the re-executed import statement actually picks up. Without
    # this, reload would repopulate any key this test just deleted straight
    # from the developer's real .env on disk (load_dotenv only skips keys
    # still PRESENT in os.environ, not ones removed above), silently
    # overriding the scenario under test. Neutralised for this reload only;
    # production code (config.py) is untouched, so every real process
    # (gunicorn, flask CLI, pytest collection) still calls the genuine
    # load_dotenv() once.
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *a, **kw: None)
    return importlib.reload(config_module)


def test_development_prefers_dev_database_url(monkeypatch):
    cfg = _reload_config(monkeypatch, {
        'DATABASE_URL': 'postgresql+pg8000://prod/prod_db',
        'DATABASE_URL_DEV': 'postgresql+pg8000://dev/dev_db',
    })
    assert cfg.DevelopmentConfig.SQLALCHEMY_DATABASE_URI == 'postgresql+pg8000://dev/dev_db'


# Ці два тести НЕ фіксують поведінку, змінену цим завданням: вони зелені
# й на старому config.py (без DATABASE_URL_DEV), бо DevelopmentConfig і
# ProductionConfig просто беруть DATABASE_URL, як і раніше. Це навмисно --
# вони охороняють від МАЙБУТНЬОЇ регресії (наприклад, якщо хтось перенесе
# читання DATABASE_URL_DEV у базовий Config, і прод тихо почне дивитись
# у dev-базу), а не доводять, що зроблена тут зміна працює. Це робить
# лише test_development_prefers_dev_database_url вище.
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
