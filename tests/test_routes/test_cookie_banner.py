"""Тести тумблера банера про cookie.

Банер ІНФОРМАЦІЙНИЙ -- він нічого не гейтить (static/js/cookie-banner.js:
аналітика працює незалежно від натискання "Прийняти"). Тому тумблер мусить
прибирати рівно одне: саме повідомлення. Перевіряємо, що разом з розміткою
зникає і скрипт (інакше сторінка тягла б зайвий запит заради мертвого
елемента), і що жодна сусідня інтеграція від цього не гасне.
"""
from tests.support.rbac import grant_role
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.user import User


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


@pytest.fixture
def admin(app):
    """flush, а не commit: db_session відкочує транзакцію після тесту, тож
    користувач не доживає до сусідніх файлів (див. test_api_v1_clients, який
    припускає <= 200 користувачів у спільній тестовій БД)."""
    u = User.create_with_password(
        f'cb-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


@pytest.fixture(autouse=True)
def restore_banner(app):
    """SiteSettings -- singleton (id=1), спільний на всю сесію тестів, а
    /admin/settings комітить усередині запиту, і цей коміт ПЕРЕЖИВАЄ відкат
    db_session-фікстури (те саме застереження -- у test_meta_pixel.py::site).
    Без явного відновлення вимкнений тут банер зник би у сусідніх файлах.
    """
    yield
    s = SiteSettings.get()
    s.show_cookie_banner = True
    db.session.commit()


@pytest.fixture
def banner_off(app):
    s = SiteSettings.get()
    s.show_cookie_banner = False
    db.session.commit()
    return s


@pytest.fixture
def banner_on(app):
    s = SiteSettings.get()
    s.show_cookie_banner = True
    db.session.commit()
    return s


class TestDefault:
    def test_enabled_by_default(self, app):
        """Дефолт true зберігає поведінку до появи тумблера."""
        assert SiteSettings.get().show_cookie_banner is True


class TestRendering:
    def test_banner_present_when_enabled(self, client, banner_on):
        html = client.get('/').get_data(as_text=True)
        assert 'id="cookie-banner"' in html
        assert 'js/cookie-banner.js' in html

    def test_banner_absent_when_disabled(self, client, banner_off):
        html = client.get('/').get_data(as_text=True)
        assert 'id="cookie-banner"' not in html

    def test_script_goes_away_with_the_markup(self, client, banner_off):
        """Скрипт живе в тому самому partial: лишити його означало б зайвий
        запит заради елемента, якого на сторінці немає."""
        html = client.get('/').get_data(as_text=True)
        assert 'js/cookie-banner.js' not in html

    def test_disabling_touches_nothing_else(self, client, banner_off):
        """Тумблер прибирає повідомлення, а не сторінку і не інші скрипти."""
        resp = client.get('/')
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert 'js/theme.js' in html
        assert 'js/i18n.js' in html

    def test_policy_link_still_reachable(self, client, banner_off):
        """Банера немає, але сама Політика Cookie лишається доступною."""
        assert client.get('/cookies').status_code in (200, 301, 302)


class TestAdminForm:
    def test_admin_can_switch_it_off(self, client, admin, banner_on):
        _login(client, admin)
        client.post('/admin/settings', data=_settings_payload(
            show_cookie_banner=None))
        assert SiteSettings.get().show_cookie_banner is False

    def test_admin_can_switch_it_back_on(self, client, admin, banner_off):
        _login(client, admin)
        client.post('/admin/settings', data=_settings_payload(
            show_cookie_banner='y'))
        assert SiteSettings.get().show_cookie_banner is True


def _settings_payload(**overrides):
    """Повний валідний POST на /admin/settings.

    Сторінка налаштувань -- ОДНА велика форма, і `populate_obj` пише геть усі
    її поля. Надіслати лише тумблер означало б занулити решту (перший підхід
    саме так і впав: NOT NULL на bank_iban). Тому payload збираємо з поточних
    значень через саму форму -- так тест не доведеться правити щоразу, коли
    в налаштуваннях з'явиться нове поле.
    """
    from wtforms import BooleanField

    from app.admin.forms import SiteSettingsForm

    site = SiteSettings.get()
    form = SiteSettingsForm(obj=site, formdata=None, meta={'csrf': False})

    data = {}
    for field in form:
        if field.name == 'csrf_token':
            continue
        if isinstance(field, BooleanField):
            # Знята галка -- це ВІДСУТНЄ поле, а не 'off'.
            if field.data:
                data[field.name] = 'y'
        elif field.data is not None:
            data[field.name] = str(field.data)

    for key, value in overrides.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return data
