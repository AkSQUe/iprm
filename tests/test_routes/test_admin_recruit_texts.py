"""Тексти запрошення тренерів редагуються в «Налаштуваннях для тренерів»."""
import pytest

from app.data.trainer_recruit import DEFAULTS
from app.extensions import db
from app.models.site_settings import SiteSettings
from tests.support.rbac import make_super_admin, switch_user

FIELDS = list(DEFAULTS)


@pytest.fixture(autouse=True)
def _no_csrf(app):
    prev = app.config.get('WTF_CSRF_ENABLED')
    app.config['WTF_CSRF_ENABLED'] = False
    yield
    app.config['WTF_CSRF_ENABLED'] = prev


@pytest.fixture
def admin(client):
    user = make_super_admin()
    db.session.commit()
    switch_user(client, user)
    return user


def _post(client, **overrides):
    data = {'faq_html': '', 'contract_email': ''}
    data.update({name: DEFAULTS[name] for name in FIELDS})
    data.update(overrides)
    return client.post('/admin/settings/trainers', data=data)


def test_form_prefilled_with_defaults(client, admin):
    html = client.get('/admin/settings/trainers').get_data(as_text=True)
    assert 'Ваш досвід може стати цінним для інших' in html
    assert 'name="recruit_page_benefits"' in html


def test_unchanged_default_is_stored_empty(client, admin):
    assert _post(client).status_code == 302
    settings = SiteSettings.get()
    assert all(getattr(settings, name) == '' for name in FIELDS)


def test_custom_text_is_stored_and_shown_on_page(client, admin):
    _post(client, recruit_page_title='Станьте голосом плазмотерапії')
    assert SiteSettings.get().recruit_page_title == 'Станьте голосом плазмотерапії'
    html = client.get('/trainers/join').get_data(as_text=True)
    assert 'Станьте голосом плазмотерапії' in html


def test_windows_line_endings_match_default(client, admin):
    _post(client, recruit_page_intro=DEFAULTS['recruit_page_intro'].replace('\n', '\r\n'))
    assert SiteSettings.get().recruit_page_intro == ''


def test_absent_fields_leave_saved_texts_untouched(client, admin):
    """Старий POST без полів запрошення не стирає збережене."""
    settings = SiteSettings.get()
    settings.recruit_page_title = 'Збережений заголовок'
    db.session.commit()
    resp = client.post('/admin/settings/trainers',
                       data={'faq_html': '', 'contract_email': ''})
    assert resp.status_code == 302
    assert SiteSettings.get().recruit_page_title == 'Збережений заголовок'


def test_present_empty_field_resets_to_default(client, admin):
    settings = SiteSettings.get()
    settings.recruit_page_title = 'Збережений заголовок'
    db.session.commit()
    _post(client, recruit_page_title='')
    assert SiteSettings.get().recruit_page_title == ''
