"""Тести інтеграції PostHog.

Головне, що тут перевіряється, -- не «скрипт вставився», а те, що рішення
НЕ РОЗХОДЯТЬСЯ між місцями, де їх приймають: наявність скрипта, дозволи CSP
і стан у налаштуваннях. Саме розходження дає найгірші відмови, і всі вони
тихі:

  * CSP без worker-src blob: -> реплей мовчки не пишеться, помилка лише в
    консолі відвідувача;
  * worker-src blob: без скрипта -> дірка в політиці без жодної користі;
  * прапорець в адмінці, що не діє -> зламаний аварійний рубильник.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.user import User

KEY = 'phc_wi73dtG77zD6oQua7i8xFERD9CYDqHYac9xcRBvEMKof'
OTHER_KEY = 'phc_' + 'b' * 30


def _csp(resp):
    return resp.headers.get('Content-Security-Policy', '')


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'ph-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


@pytest.fixture
def posthog_on(app):
    """PostHog увімкнено явно через БД."""
    s = SiteSettings.get()
    s.posthog_project_api_key = KEY
    s.posthog_enabled = True
    s.posthog_session_recording = True
    s.posthog_exclude_admin = False
    db.session.flush()
    return s


@pytest.fixture
def posthog_env_only(app):
    """Прод-подібний стан: ключ приходить з env, у БД порожньо і прапорці
    не задані (NULL)."""
    s = SiteSettings.get()
    s.posthog_project_api_key = ''
    s.posthog_enabled = None
    s.posthog_session_recording = None
    s.posthog_exclude_admin = None
    db.session.flush()
    app.config['POSTHOG_PROJECT_API_KEY'] = KEY
    app.config['POSTHOG_ENABLED'] = True
    app.config['POSTHOG_SESSION_RECORDING'] = False
    app.config['POSTHOG_EXCLUDE_ADMIN'] = False
    return s


class TestKeyValidation:
    @pytest.mark.parametrize('value', ['', KEY, 'phc_' + 'a' * 20,
                                       'phc_' + 'a' * 18 + '-_'])
    def test_valid_keys_accepted(self, app, value):
        assert SiteSettings.is_valid_posthog_key(value) is True

    @pytest.mark.parametrize('value', [
        'phx_abcdefghijklmnopqrstuvwx',   # Personal API Key -- читає дані проєкту
        'phc_short',                       # хвіст закороткий
        'G-T2LHJ436ZG',                    # переплутали з GA
        'phc_has spaces in it here ok',
    ])
    def test_invalid_keys_rejected(self, app, value):
        assert SiteSettings.is_valid_posthog_key(value) is False


class TestKillSwitch:
    """Прапорець в адмінці мусить діяти НЕЗАЛЕЖНО від джерела ключа.

    Це регресійні тести на реальний дефект: доти прапорець дивився на
    наявність ключа В БД, тож на проді (ключ з env) вимкнення в адмінці
    мовчки ігнорувалось, а галка реплею не робила нічого.
    """

    def test_disabling_in_admin_beats_env_key(self, app, posthog_env_only):
        s = posthog_env_only
        s.posthog_enabled = False
        db.session.flush()
        assert s.effective_posthog_api_key == '', (
            'аварійний рубильник не спрацював при ключі з env'
        )

    def test_enabling_recording_in_admin_beats_env(self, app, posthog_env_only):
        s = posthog_env_only
        s.posthog_session_recording = True
        db.session.flush()
        assert s.effective_posthog_session_recording is True, (
            'галка реплею інертна при ключі з env'
        )

    def test_disabling_in_admin_beats_db_key(self, app):
        s = SiteSettings.get()
        s.posthog_project_api_key = KEY
        s.posthog_enabled = False
        db.session.flush()
        app.config['POSTHOG_PROJECT_API_KEY'] = OTHER_KEY
        app.config['POSTHOG_ENABLED'] = True
        assert s.effective_posthog_api_key == ''

    def test_null_flag_inherits_env(self, app, posthog_env_only):
        """NULL означає «в адмінці не задано» -- вирішує env."""
        assert posthog_env_only.posthog_enabled is None
        assert posthog_env_only.effective_posthog_api_key == KEY

    def test_db_key_wins_over_env_key(self, app, posthog_env_only):
        s = posthog_env_only
        s.posthog_project_api_key = OTHER_KEY
        db.session.flush()
        assert s.effective_posthog_api_key == OTHER_KEY

    def test_recording_requires_analytics(self, app):
        s = SiteSettings.get()
        s.posthog_project_api_key = KEY
        s.posthog_enabled = False
        s.posthog_session_recording = True
        db.session.flush()
        app.config['POSTHOG_PROJECT_API_KEY'] = ''
        assert s.effective_posthog_session_recording is False


class TestScriptInjection:
    def test_absent_when_not_configured(self, app, client):
        app.config['POSTHOG_PROJECT_API_KEY'] = ''
        app.config['POSTHOG_ENABLED'] = False
        html = client.get('/').get_data(as_text=True)
        assert 'js/posthog.js' not in html

    def test_present_when_configured(self, client, posthog_on):
        html = client.get('/').get_data(as_text=True)
        assert 'js/posthog.js' in html
        assert f'data-ph-key="{KEY}"' in html
        assert 'data-ph-api-host="/ngx-e"' in html

    def test_events_handler_follows_the_script(self, client, posthog_on):
        html = client.get('/').get_data(as_text=True)
        assert 'js/analytics-events.js' in html

    def test_api_host_trailing_slash_normalized(self, app, client, posthog_on):
        """'/ngx-e/' у конфізі не повинно давати '//static/array.js'."""
        app.config['POSTHOG_API_HOST'] = '/ngx-e/'
        html = client.get('/').get_data(as_text=True)
        assert 'data-ph-api-host="/ngx-e"' in html


class TestSectionAndMasking:
    def test_public_page_reports_its_blueprint(self, client, posthog_on):
        html = client.get('/').get_data(as_text=True)
        assert 'data-ph-section="main"' in html

    def test_public_page_masks_only_marked_text(self, client, posthog_on):
        html = client.get('/').get_data(as_text=True)
        assert 'data-ph-mask-all-text="0"' in html

    def test_admin_masks_all_text(self, client, admin, posthog_on):
        """maskAllInputs ховає лише те, що вводять; списки учасників з ПІБ і
        медпрофілями вже відрендерені й без цього поїхали б у відеозапис."""
        _login(client, admin)
        html = client.get('/admin/settings').get_data(as_text=True)
        assert 'data-ph-section="admin"' in html
        assert 'data-ph-mask-all-text="1"' in html

    def test_identify_carries_no_name(self, client, admin, posthog_on):
        _login(client, admin)
        html = client.get('/admin/settings').get_data(as_text=True)
        assert f'data-ph-user-id="{admin.id}"' in html
        assert 'data-ph-role="admin"' in html
        assert admin.first_name not in html.split('data-ph-key')[1][:600]


class TestExcludeAdmin:
    def test_admin_tracked_by_default(self, client, admin, posthog_on):
        _login(client, admin)
        html = client.get('/admin/settings').get_data(as_text=True)
        assert 'js/posthog.js' in html

    def test_admin_dropped_when_excluded(self, client, admin, posthog_on):
        posthog_on.posthog_exclude_admin = True
        db.session.flush()
        _login(client, admin)
        html = client.get('/admin/settings').get_data(as_text=True)
        assert 'js/posthog.js' not in html

    def test_public_still_tracked_when_admin_excluded(self, client, posthog_on):
        posthog_on.posthog_exclude_admin = True
        db.session.flush()
        html = client.get('/').get_data(as_text=True)
        assert 'js/posthog.js' in html

    def test_test_page_stays_tracked(self, client, admin, posthog_on):
        """Сторінка перевірки лишається під трекінгом навіть при винятку --
        інакше перевіряти було б нічого."""
        posthog_on.posthog_exclude_admin = True
        db.session.flush()
        _login(client, admin)
        html = client.get('/admin/posthog/test').get_data(as_text=True)
        assert 'js/posthog.js' in html


class TestCSP:
    def test_worker_src_absent_without_posthog(self, app, client):
        app.config['POSTHOG_PROJECT_API_KEY'] = ''
        app.config['POSTHOG_ENABLED'] = False
        assert 'worker-src' not in _csp(client.get('/'))

    def test_worker_src_present_with_posthog(self, client, posthog_on):
        """rrweb стискає реплей у Web Worker з blob:; без цієї директиви
        політика падає на default-src 'self' і воркер блокується."""
        assert "worker-src 'self' blob:" in _csp(client.get('/'))

    def test_ui_host_allowed_for_toolbar(self, client, posthog_on):
        assert 'https://eu.posthog.com' in _csp(client.get('/'))

    def test_ingestion_needs_no_extra_connect_src(self, client, posthog_on):
        """Сенс проксі: події йдуть на власний домен, тож доменів PostHog у
        connect-src бути не повинно -- 'self' їх покриває."""
        csp = _csp(client.get('/'))
        assert 'eu.i.posthog.com' not in csp
        assert 'eu-assets.i.posthog.com' not in csp


class TestAdminForm:
    def test_save_rejects_personal_api_key(self, client, admin, posthog_on):
        _login(client, admin)
        r = client.post('/admin/posthog/save', data={
            'posthog_project_api_key': 'phx_' + 'a' * 30,
            'posthog_enabled': 'on',
        }, follow_redirects=True)
        assert r.status_code == 200
        assert SiteSettings.get().posthog_project_api_key == KEY

    def test_cannot_enable_without_any_key(self, app, client, admin):
        app.config['POSTHOG_PROJECT_API_KEY'] = ''
        s = SiteSettings.get()
        s.posthog_project_api_key = ''
        s.posthog_enabled = None
        db.session.flush()
        _login(client, admin)
        client.post('/admin/posthog/save', data={'posthog_enabled': 'on'},
                    follow_redirects=True)
        assert SiteSettings.get().posthog_enabled is not True

    def test_cannot_record_without_analytics(self, client, admin, posthog_on):
        # Стартуємо з вимкненого реплею, інакше тест не відрізнив би
        # відхилену форму від успішно збереженої.
        posthog_on.posthog_session_recording = False
        db.session.flush()
        _login(client, admin)
        client.post('/admin/posthog/save', data={
            'posthog_project_api_key': KEY,
            'posthog_session_recording': 'on',
        }, follow_redirects=True)
        assert SiteSettings.get().posthog_session_recording is not True

    def test_save_makes_flags_explicit(self, client, admin, posthog_env_only):
        """Після збереження рішення належить БД, а не env -- інакше
        рубильник знову став би декоративним."""
        _login(client, admin)
        client.post('/admin/posthog/save', data={
            'posthog_project_api_key': '',
        }, follow_redirects=True)
        s = SiteSettings.get()
        assert s.posthog_enabled is False
        assert s.effective_posthog_api_key == ''
