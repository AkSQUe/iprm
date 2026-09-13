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
from tests.support.rbac import grant_role
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


@pytest.fixture(autouse=True)
def _isolate_posthog(app):
    """Повернути PostHog у вихідний стан після кожного тесту.

    Тестова БД і app.config спільні на всю pytest-сесію, а маршрути
    збереження роблять commit. Без цього увімкнений тут PostHog переживав
    файл, і сторінки в чужих тестах рендерили data-ph-email залогіненого
    користувача -- test_user_roles падав на "email не має бути в HTML" лише
    в повному прогоні.
    """
    config_snapshot = {k: v for k, v in app.config.items() if k.startswith('POSTHOG_')}
    yield
    db.session.rollback()
    s = SiteSettings.get()
    s.posthog_project_api_key = ''
    s.posthog_enabled = None
    s.posthog_session_recording = None
    s.posthog_exclude_admin = None
    s.posthog_secondary_api_key = ''
    s.posthog_secondary_session_recording = False
    db.session.commit()
    for k in [k for k in app.config if k.startswith('POSTHOG_')]:
        del app.config[k]
    app.config.update(config_snapshot)


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'ph-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
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


class TestSecondaryProject:
    """Додатковий проєкт: ті самі події в другий проєкт PostHog.

    Головне тут -- що аварійні рубильники лишились спільними. Другий проєкт,
    який переживає вимкнення аналітики чи реплею, робив би рубильник
    неповним, і найгірше, що помітити це з адмінки було б неможливо.
    """

    def test_absent_by_default(self, client, posthog_on):
        html = client.get('/').get_data(as_text=True)
        assert 'data-ph-secondary-key' not in html

    def test_injected_when_set(self, client, posthog_on):
        posthog_on.posthog_secondary_api_key = OTHER_KEY
        db.session.flush()
        html = client.get('/').get_data(as_text=True)
        assert f'data-ph-key="{KEY}"' in html
        assert f'data-ph-secondary-key="{OTHER_KEY}"' in html
        assert 'data-ph-secondary-recording="0"' in html

    def test_kill_switch_silences_secondary(self, app, posthog_on):
        posthog_on.posthog_secondary_api_key = OTHER_KEY
        posthog_on.posthog_enabled = False
        db.session.flush()
        assert posthog_on.effective_posthog_secondary_api_key == ''

    def test_works_with_env_primary_key(self, app, posthog_env_only):
        posthog_env_only.posthog_secondary_api_key = OTHER_KEY
        db.session.flush()
        assert posthog_env_only.effective_posthog_secondary_api_key == OTHER_KEY

    def test_same_key_is_not_duplicated(self, app, posthog_on):
        """Той самий ключ двічі -- кожна подія рахувалась би вдвічі."""
        posthog_on.posthog_secondary_api_key = KEY
        db.session.flush()
        assert posthog_on.effective_posthog_secondary_api_key == ''

    def test_recording_off_by_default(self, app, posthog_on):
        posthog_on.posthog_secondary_api_key = OTHER_KEY
        db.session.flush()
        assert posthog_on.effective_posthog_session_recording is True
        assert posthog_on.effective_posthog_secondary_session_recording is False

    def test_recording_kill_switch_covers_secondary(self, app, posthog_on):
        posthog_on.posthog_secondary_api_key = OTHER_KEY
        posthog_on.posthog_secondary_session_recording = True
        posthog_on.posthog_session_recording = False
        db.session.flush()
        assert posthog_on.effective_posthog_secondary_session_recording is False

    def test_recording_enabled_explicitly(self, client, posthog_on):
        posthog_on.posthog_secondary_api_key = OTHER_KEY
        posthog_on.posthog_secondary_session_recording = True
        db.session.flush()
        html = client.get('/').get_data(as_text=True)
        assert 'data-ph-secondary-recording="1"' in html

    def test_save_stores_secondary(self, client, admin, posthog_on):
        _login(client, admin)
        client.post('/admin/posthog/save', data={
            'posthog_project_api_key': KEY,
            'posthog_enabled': 'on',
            'posthog_secondary_api_key': OTHER_KEY,
        }, follow_redirects=True)
        s = SiteSettings.get()
        assert s.posthog_secondary_api_key == OTHER_KEY
        assert s.posthog_secondary_session_recording is False

    def test_save_rejects_personal_key_as_secondary(self, client, admin, posthog_on):
        _login(client, admin)
        client.post('/admin/posthog/save', data={
            'posthog_project_api_key': KEY,
            'posthog_enabled': 'on',
            'posthog_secondary_api_key': 'phx_' + 'a' * 30,
        }, follow_redirects=True)
        assert SiteSettings.get().posthog_secondary_api_key == ''

    def test_save_rejects_duplicate_of_env_key(self, app, client, admin, posthog_env_only):
        _login(client, admin)
        client.post('/admin/posthog/save', data={
            'posthog_project_api_key': '',
            'posthog_enabled': 'on',
            'posthog_secondary_api_key': KEY,
        }, follow_redirects=True)
        assert SiteSettings.get().posthog_secondary_api_key == ''

    def test_page_shows_secondary(self, client, admin, posthog_on):
        posthog_on.posthog_secondary_api_key = OTHER_KEY
        db.session.flush()
        _login(client, admin)
        html = client.get('/admin/posthog').get_data(as_text=True)
        assert 'Два проєкти' in html
        assert f'value="{OTHER_KEY}"' in html

    def test_test_page_probes_secondary(self, client, admin, posthog_on):
        posthog_on.posthog_secondary_api_key = OTHER_KEY
        db.session.flush()
        _login(client, admin)
        html = client.get('/admin/posthog/test').get_data(as_text=True)
        assert 'ph-check-array-secondary' in html


class TestSettingsRules:
    """Правила збереження живуть у сервісі, щоб форма й імпорт .env не
    розійшлись: імпорт спершу обходив їх повністю."""

    def test_personal_key_rejected(self, app):
        from app.services.posthog import posthog_keys_error
        assert posthog_keys_error('phx_' + 'a' * 30, '')

    def test_secondary_personal_key_named_in_error(self, app):
        from app.services.posthog import posthog_keys_error
        assert 'Додатковий' in posthog_keys_error(KEY, 'phx_' + 'a' * 30)

    def test_duplicate_of_env_key_rejected(self, app):
        from app.services.posthog import posthog_keys_error
        assert posthog_keys_error('', KEY, env_key=KEY)

    def test_valid_pair_passes(self, app):
        from app.services.posthog import posthog_settings_error
        assert posthog_settings_error(
            api_key=KEY, secondary_key=OTHER_KEY, enabled=True,
            recording=True, secondary_recording=True) is None


class TestImportValidation:
    """Імпорт .env не має пропускати в HTML Personal API Key."""

    def test_preview_shows_error_and_hides_apply(self, client, admin, posthog_on):
        _login(client, admin)
        html = client.post('/admin/integrations/import-preview', data={
            'env_text': 'POSTHOG_PROJECT_API_KEY=phx_' + 'a' * 30,
        }).get_data(as_text=True)
        assert 'Personal API Key' in html
        assert 'integrations/import-apply' not in html

    def test_apply_refuses_personal_key(self, client, admin, posthog_on):
        _login(client, admin)
        client.post('/admin/integrations/import-apply', data={
            'env_text': 'POSTHOG_SECONDARY_API_KEY=phx_' + 'a' * 30,
        })
        assert SiteSettings.get().posthog_secondary_api_key == ''

    def test_apply_refuses_duplicate_across_db_and_file(self, client, admin, posthog_on):
        """Основний ключ у БД, додатковий -- у файлі: дубль видно лише зі
        стану ПІСЛЯ імпорту."""
        _login(client, admin)
        client.post('/admin/integrations/import-apply', data={
            'env_text': f'POSTHOG_SECONDARY_API_KEY={KEY}',
        })
        assert SiteSettings.get().posthog_secondary_api_key == ''

    def test_valid_import_applies(self, client, admin, posthog_on):
        _login(client, admin)
        client.post('/admin/integrations/import-apply', data={
            'env_text': f'POSTHOG_SECONDARY_API_KEY={OTHER_KEY}',
        })
        assert SiteSettings.get().posthog_secondary_api_key == OTHER_KEY


class TestFormDraft:
    def test_rejected_input_survives_redirect(self, client, admin, posthog_on):
        _login(client, admin)
        bad = 'phx_' + 'c' * 30
        client.post('/admin/posthog/save', data={
            'posthog_project_api_key': KEY,
            'posthog_enabled': 'on',
            'posthog_secondary_api_key': bad,
        })
        html = client.get('/admin/posthog').get_data(as_text=True)
        assert f'value="{bad}"' in html
        # Чернетка одноразова: наступний показ -- знову збережений стан.
        html = client.get('/admin/posthog').get_data(as_text=True)
        assert f'value="{bad}"' not in html


class TestHealthCheck:
    def test_absolute_api_host_is_degraded(self, app, posthog_on, monkeypatch):
        """Абсолютний хост CSP блокує -- зелений статус тут означав би нуль
        даних під зеленою галкою."""
        from app.services.integration_health import HealthStatus, _check_posthog
        # monkeypatch, а не пряме присвоєння: конфіг застосунку спільний між
        # тестами, і абсолютний хост ламав би розмітку в наступних.
        monkeypatch.setitem(app.config, 'POSTHOG_API_HOST', 'https://eu.i.posthog.com')
        assert _check_posthog(posthog_on)['status'] == HealthStatus.DEGRADED

    def test_card_says_disabled_for_env_key(self, app, client, admin, posthog_env_only):
        posthog_env_only.posthog_enabled = False
        db.session.flush()
        _login(client, admin)
        html = client.get('/admin/integrations').get_data(as_text=True)
        # Рівно до кінця картки: далі йде Meta Pixel зі своїм бейджем.
        card = html.split('>PostHog</h4>', 1)[1].split('</a>', 1)[0]
        assert 'Вимкнено' in card
        assert 'Не налаштовано' not in card


class TestClientScript:
    """Поведінку SDK тут не виконати, тож стережемо саму наявність захисту
    в скрипті -- його зникнення повертає дефект тихо."""

    def _js(self, name):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / 'app' / 'static' / 'js'
        return (root / name).read_text(encoding='utf-8')

    def test_identity_reset_after_logout(self):
        js = self._js('posthog.js')
        assert "get_property('$user_state')" in js
        assert 'instance.reset()' in js
        assert js.index('instance.reset()') < js.index('instance.register('), (
            'reset стирає супервластивості, тож має йти ДО register'
        )

    def test_instance_names_come_from_one_place(self):
        for name in ('analytics-events.js', 'admin-posthog-test.js'):
            js = self._js(name)
            assert 'iprmPosthogInstances' in js
            assert "'secondary'" not in js


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
        assert 'data-ph-role="staff"' in html
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


class TestPurchaseMarkup:
    """Подія purchase має бути розмічена на ОБОХ сторінках успіху.

    Доти її не було ніде: Meta бачила покупки лише для заходів, а GA4 і
    PostHog обривались на begin_checkout -- воронка закінчувалась
    натисканням кнопки, і рекламу можна було оптимізувати під сабміти форм,
    а не під гроші. Онлайн-курси не трекались зовсім.
    """

    def _markup(self, name):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / 'app' / 'templates'
        return (root / name).read_text(encoding='utf-8')

    @pytest.mark.parametrize('template', [
        'payments/success.html', 'online/success.html',
    ])
    def test_sends_purchase_to_all_three_sinks(self, template):
        html = self._markup(template)
        assert 'data-ga-event-load="purchase"' in html, 'GA4 і PostHog не отримають покупку'
        assert 'data-meta-event-load="Purchase"' in html, 'Meta не отримає покупку'

    @pytest.mark.parametrize('template', [
        'payments/success.html', 'online/success.html',
    ])
    def test_purchase_is_deduplicated(self, template):
        """Сторінку успіху відкривають повторно (F5, "назад" після редиректу
        LiqPay). Без стабільного ID кожен перегляд рахувався б покупкою."""
        html = self._markup(template)
        assert 'data-ga-event-id=' in html
        assert 'data-meta-event-id=' in html

    @pytest.mark.parametrize('template', [
        'payments/success.html', 'online/success.html',
    ])
    def test_purchase_carries_value_and_currency(self, template):
        html = self._markup(template)
        assert 'data-ga-param-value=' in html
        assert 'data-ga-param-currency="UAH"' in html


class TestCspScope:
    """CSP рахує дозволи сторонніх доменів лише для HTML.

    Хук after_request спрацьовує на КОЖНУ відповідь -- включно з JSON API
    і редиректами, де скрипти не виконуються взагалі. Для них політика
    лишається базовою: це строгіше, а не слабше.
    """

    def test_html_keeps_third_party_allowances(self, client, posthog_on):
        resp = client.get('/')
        assert resp.mimetype == 'text/html'
        assert 'https://eu.posthog.com' in _csp(resp)

    def test_non_html_has_no_third_party_allowances(self, client, posthog_on):
        resp = client.get('/sitemap.xml')
        assert resp.status_code == 200
        assert not resp.mimetype.startswith('text/html')
        csp = _csp(resp)
        assert csp, 'CSP не має зникати на не-HTML відповідях'
        assert 'posthog.com' not in csp
        assert 'worker-src' not in csp

    def test_non_html_still_carries_base_headers(self, client, posthog_on):
        resp = client.get('/sitemap.xml')
        assert resp.headers.get('X-Content-Type-Options') == 'nosniff'
        assert resp.headers.get('X-Frame-Options') == 'DENY'


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
