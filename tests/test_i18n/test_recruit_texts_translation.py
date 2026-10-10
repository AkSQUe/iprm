"""Переклад власного тексту запрошення доходить до англійської сторінки."""
import pytest
from markupsafe import Markup

from app.extensions import db
from app.models.site_settings import SiteSettings
from tests.support.rbac import make_super_admin, switch_user


@pytest.fixture(autouse=True)
def _no_csrf(app):
    prev = app.config.get('WTF_CSRF_ENABLED')
    app.config['WTF_CSRF_ENABLED'] = False
    yield
    app.config['WTF_CSRF_ENABLED'] = prev


def test_translation_of_custom_text_reaches_english_page(client, get_localized):
    user = make_super_admin()
    db.session.commit()
    switch_user(client, user)
    settings = SiteSettings.get()
    settings.recruit_page_title = 'Станьте голосом плазмотерапії'
    settings.set_translation('en', 'recruit_page_title', 'Become the voice of plasma therapy')
    db.session.commit()
    # Видимий текст: останнє слово заголовка загорнуте в градієнтний <span>.
    html = Markup(get_localized('/en/trainers/join').get_data(as_text=True)).striptags()
    assert 'Become the voice of plasma therapy' in html
