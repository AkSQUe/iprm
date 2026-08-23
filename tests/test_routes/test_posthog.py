"""Тести інтеграції PostHog.

Головне, що тут перевіряється, -- не "скрипт вставився", а те, що ТРИ
рішення не розходяться: наявність скрипта, дозволи CSP і стан у налаштуваннях.
Саме розходження дає найгірші відмови, і всі вони тихі:

  * CSP без worker-src blob: -> реплей мовчки не пишеться, помилка лише в
    консолі відвідувача;
  * worker-src blob: без скрипта -> дірка в політиці без жодної користі;
  * ключ у БД при знятому прапорці -> "вимкнув в адмінці, а воно й далі шле".
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.user import User

KEY = 'phc_wi73dtG77zD6oQua7i8xFERD9CYDqHYac9xcRBvEMKof'


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
    """PostHog увімкнено через БД (не env) -- як воно й буде в проді."""
    s = SiteSettings.get()
    s.posthog_project_api_key = KEY
    s.posthog_enabled = True
    s.posthog_session_recording = True
    db.session.flush()
    return s


class TestKeyValidation:
    @pytest.mark.parametrize('value', ['', KEY, 'phc_' + 'a' * 20])
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


class TestEffectiveKey:
    def test_key_without_flag_is_off(self, app):
        """Ключ збережено, прапорець знято -- трекінгу немає.

        Це та сама пастка, від якої захищений Meta Pixel: env-fallback НЕ
        має підміняти свідоме вимкнення в адмінці.
        """
        s = SiteSettings.get()
        s.posthog_project_api_key = KEY
        s.posthog_enabled = False
        db.session.flush()
        app.config['POSTHOG_PROJECT_API_KEY'] = 'phc_' + 'b' * 30
        app.config['POSTHOG_ENABLED'] = True
        assert s.effective_posthog_api_key == ''

    def test_env_fallback_used_when_db_empty(self, app):
        s = SiteSettings.get()
        s.posthog_project_api_key = ''
        db.session.flush()
        app.config['POSTHOG_PROJECT_API_KEY'] = KEY
        app.config['POSTHOG_ENABLED'] = True
        assert s.effective_posthog_api_key == KEY

    def test_recording_requires_analytics(self, app):
        """Запис сесій без активної аналітики -- завжди вимкнений."""
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
        """posthog-events.js підключається рівно тоді, коли є сам SDK."""
        html = client.get('/').get_data(as_text=True)
        assert 'js/posthog-events.js' in html


class TestSectionProperty:
    """iprm_section -- заміна вимиканню трекінгу в адмінці: збираємо скрізь,
    а внутрішній трафік фільтрується в UI PostHog."""

    def test_public_page_reports_its_blueprint(self, client, posthog_on):
        html = client.get('/').get_data(as_text=True)
        assert 'data-ph-section="main"' in html

    def test_public_page_masks_only_marked_text(self, client, posthog_on):
        html = client.get('/').get_data(as_text=True)
        assert 'data-ph-mask-all-text="0"' in html

    def test_admin_masks_all_text(self, client, admin, posthog_on):
        """В адмінці реплей мусить маскувати ВЕСЬ текст.

        maskAllInputs ховає лише те, що вводять; списки учасників з ПІБ,
        телефонами і медпрофілями вже відрендерені на сторінці й без цього
        потрапили б у відеозапис.
        """
        _login(client, admin)
        html = client.get('/admin/settings').get_data(as_text=True)
        assert 'data-ph-section="admin"' in html
        assert 'data-ph-mask-all-text="1"' in html

    def test_identify_carries_no_name(self, client, admin, posthog_on):
        """identify шле email і роль, але не ПІБ: ім'я в PostHog не потрібне
        для жодного звіту, а PII туди виїжджає назавжди."""
        _login(client, admin)
        html = client.get('/admin/settings').get_data(as_text=True)
        assert f'data-ph-user-id="{admin.id}"' in html
        assert 'data-ph-role="admin"' in html
        assert admin.first_name not in html.split('data-ph-key')[1][:600]


class TestCSP:
    def test_worker_src_absent_without_posthog(self, app, client):
        """Без PostHog worker-src blob: -- зайва дірка."""
        app.config['POSTHOG_PROJECT_API_KEY'] = ''
        app.config['POSTHOG_ENABLED'] = False
        assert 'worker-src' not in _csp(client.get('/'))

    def test_worker_src_present_with_posthog(self, client, posthog_on):
        """Без цієї директиви реплей мовчки не пише: rrweb стискає дані у
        Web Worker з blob:, а політика без worker-src падає на
        default-src 'self' і воркер блокується."""
        csp = _csp(client.get('/'))
        assert "worker-src 'self' blob:" in csp

    def test_ui_host_allowed_for_toolbar(self, client, posthog_on):
        csp = _csp(client.get('/'))
        assert 'https://eu.posthog.com' in csp

    def test_ingestion_needs_no_extra_connect_src(self, client, posthog_on):
        """Сенс проксі: події йдуть на власний домен, тож доменів PostHog у
        connect-src бути не повинно -- 'self' їх покриває."""
        csp = _csp(client.get('/'))
        assert 'eu.i.posthog.com' not in csp
        assert 'eu-assets.i.posthog.com' not in csp
