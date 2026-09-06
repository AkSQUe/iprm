"""Тести інтеграції Google Analytics 4.

Головне тут -- аварійний рубильник. До появи прапорця вимикача в GA не було
взагалі: єдиним важелем в адмінці лишалось поле Measurement ID, а порожнє
поле означало не "вимкнути", а "взяти з env" -- де в ProductionConfig вшитий
реальний G-T2LHJ436ZG. Адміністратор стирав ID, бачив "Збережено" і далі слав
дані в Google. Той самий дефект уже ловили в PostHog
(test_posthog.py::TestKillSwitch); тут -- його GA-двійник.

Друге, що перевіряється, -- що рішення НЕ РОЗХОДЯТЬСЯ між місцями, де їх
приймають: наявність скрипта, дозволи доменів Google у CSP і стан у
налаштуваннях. Розходження дає тихі відмови: CSP без доменів -> gtag.js
блокується і в GA нуль даних; домени без скрипта -> дірка в політиці без
жодної користі.
"""
from tests.support.rbac import grant_role
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.user import User

GA_ID = 'G-T2LHJ436ZG'
OTHER_GA_ID = 'G-ABCDEFGH12'


def _csp(resp):
    return resp.headers.get('Content-Security-Policy', '')


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'ga-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


@pytest.fixture
def ga_on(app):
    """GA увімкнено явно через БД."""
    s = SiteSettings.get()
    s.google_analytics_id = GA_ID
    s.google_analytics_enabled = True
    db.session.flush()
    return s


@pytest.fixture
def ga_env_only(app):
    """Прод-подібний стан: ID приходить з env, у БД порожньо і прапорець не
    заданий (NULL)."""
    s = SiteSettings.get()
    s.google_analytics_id = ''
    s.google_analytics_enabled = None
    db.session.flush()
    app.config['GOOGLE_ANALYTICS_ID'] = GA_ID
    app.config['GOOGLE_ANALYTICS_ENABLED'] = True
    return s


class TestIdValidation:
    @pytest.mark.parametrize('value', ['', GA_ID, 'G-ABCD', 'G-' + 'A' * 20])
    def test_valid_ids_accepted(self, app, value):
        assert SiteSettings.is_valid_ga_id(value) is True

    @pytest.mark.parametrize('value', [
        'phc_wi73dtG77zD6oQua7i8xFERD9CYDqHYac9xcRB',  # переплутали з PostHog
        'UA-12345-1',                                   # Universal Analytics
        'G-abc',                                        # хвіст закороткий
        'G-HAS SPACES',
    ])
    def test_invalid_ids_rejected(self, app, value):
        assert SiteSettings.is_valid_ga_id(value) is False


class TestKillSwitch:
    """Прапорець в адмінці мусить діяти НЕЗАЛЕЖНО від джерела ID.

    Регресія на реальний дефект: вимикача не існувало, і стирання ID в
    адмінці на проді мовчки ігнорувалось -- порожнє поле лише перемикало
    джерело на env, де лежить той самий Measurement ID.
    """

    def test_disabling_in_admin_beats_env_id(self, app, ga_env_only):
        s = ga_env_only
        s.google_analytics_enabled = False
        db.session.flush()
        assert s.effective_google_analytics_id == '', (
            'аварійний рубильник не спрацював при ID з env'
        )

    def test_disabling_in_admin_beats_db_id(self, app):
        s = SiteSettings.get()
        s.google_analytics_id = GA_ID
        s.google_analytics_enabled = False
        db.session.flush()
        app.config['GOOGLE_ANALYTICS_ID'] = OTHER_GA_ID
        app.config['GOOGLE_ANALYTICS_ENABLED'] = True
        assert s.effective_google_analytics_id == ''

    def test_clearing_id_no_longer_pretends_to_be_a_switch(self, app, ga_env_only):
        """Порожнє поле ID -- це "брати з env", а не "вимкнути". Саме ця
        двозначність і була дефектом: тепер вимикає лише галка."""
        s = ga_env_only
        s.google_analytics_id = ''
        s.google_analytics_enabled = True
        db.session.flush()
        assert s.effective_google_analytics_id == GA_ID

    def test_enabling_in_admin_beats_env(self, app, ga_env_only):
        s = ga_env_only
        app.config['GOOGLE_ANALYTICS_ENABLED'] = False
        s.google_analytics_enabled = True
        db.session.flush()
        assert s.effective_google_analytics_id == GA_ID

    def test_null_flag_inherits_env(self, app, ga_env_only):
        """NULL означає "в адмінці не задано" -- вирішує env."""
        assert ga_env_only.google_analytics_enabled is None
        assert ga_env_only.effective_google_analytics_id == GA_ID

    def test_null_flag_inherits_env_disabled(self, app, ga_env_only):
        app.config['GOOGLE_ANALYTICS_ENABLED'] = False
        assert ga_env_only.effective_google_analytics_id == ''

    def test_db_id_wins_over_env_id(self, app, ga_env_only):
        s = ga_env_only
        s.google_analytics_id = OTHER_GA_ID
        db.session.flush()
        assert s.effective_google_analytics_id == OTHER_GA_ID


class TestScriptInjection:
    def test_absent_when_disabled(self, app, client, ga_env_only):
        ga_env_only.google_analytics_enabled = False
        db.session.flush()
        html = client.get('/').get_data(as_text=True)
        assert 'js/analytics.js' not in html

    def test_present_when_enabled(self, client, ga_on):
        html = client.get('/').get_data(as_text=True)
        assert 'js/analytics.js' in html
        assert f'data-ga-id="{GA_ID}"' in html
        assert 'data-ga-transport="/ngx-i"' in html

    def test_loader_goes_through_first_party_proxy(self, client, ga_on):
        """gtag.js не підключається розміткою: його адреса їде в
        data-ga-loader, а вставляє його analytics.js після рендеру."""
        html = client.get('/').get_data(as_text=True)
        assert f'data-ga-loader="/ngx-i/loader.js?id={GA_ID}"' in html
        assert 'googletagmanager.com/gtag/js' not in html


class TestCSP:
    def test_google_domains_absent_when_disabled(self, app, client, ga_env_only):
        ga_env_only.google_analytics_enabled = False
        db.session.flush()
        assert 'google-analytics.com' not in _csp(client.get('/'))

    def test_google_domains_present_when_enabled(self, client, ga_on):
        """Без цих доменів gtag.js і маяки збору блокуються -> нуль даних."""
        csp = _csp(client.get('/'))
        assert 'https://www.googletagmanager.com' in csp
        assert 'https://www.google-analytics.com' in csp


class TestAdminForm:
    def test_save_disables_and_keeps_id(self, client, admin, ga_on):
        """Знята галка гасить трекінг, але Measurement ID лишається -- щоб
        увімкнути назад не довелось шукати його заново."""
        _login(client, admin)
        client.post('/admin/google-analytics/save',
                    data={'google_analytics_id': GA_ID})
        s = SiteSettings.get()
        assert s.google_analytics_enabled is False
        assert s.google_analytics_id == GA_ID
        assert s.effective_google_analytics_id == ''

    def test_save_makes_flag_explicit(self, client, admin, ga_env_only):
        """Будь-яке збереження знімає стан "вирішує env": після свідомого
        тику рішення належить адмінці."""
        _login(client, admin)
        client.post('/admin/google-analytics/save',
                    data={'google_analytics_id': '',
                          'google_analytics_enabled': 'on'})
        assert SiteSettings.get().google_analytics_enabled is True

    def test_cannot_enable_without_any_id(self, app, client, admin):
        _login(client, admin)
        s = SiteSettings.get()
        s.google_analytics_id = ''
        s.google_analytics_enabled = None
        db.session.flush()
        app.config['GOOGLE_ANALYTICS_ID'] = ''
        client.post('/admin/google-analytics/save',
                    data={'google_analytics_id': '',
                          'google_analytics_enabled': 'on'})
        assert SiteSettings.get().google_analytics_enabled is not True

    def test_invalid_id_rejected(self, client, admin, ga_on):
        _login(client, admin)
        client.post('/admin/google-analytics/save',
                    data={'google_analytics_id': 'UA-12345-1',
                          'google_analytics_enabled': 'on'})
        assert SiteSettings.get().google_analytics_id == GA_ID
