"""Локальні фікстури i18n-тестів.

Flask-Babel кешує обрану локаль на g._flask_babel. Session-scoped app-фікстура
тримає один app-контекст, тож `g` спільний між запитами (у проді кожен HTTP-
запит ізольований -- це суто тест-артефакт). Чистимо кеш перед кожним тестом і
надаємо хелпер get_localized для перевірок кількох локалей в одному тесті.
"""
import pytest
from flask import g


def _clear_babel():
    try:
        g.pop('_flask_babel', None)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_locale_cache(app):
    _clear_babel()
    yield
    _clear_babel()


@pytest.fixture
def get_localized(client):
    """GET зі скиданням кешу локалі -- для порівняння кількох мов в одному тесті."""
    def _get(url):
        _clear_babel()
        return client.get(url)
    return _get
