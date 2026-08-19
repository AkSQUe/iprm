"""Тести клієнта Meta Graph API.

Мережі тут немає: `requests.request` підмінюється, `sleep` -- теж, інакше
ретраї перетворили б набір на секунди очікування. Бази немає й поготів --
клієнт про неї нічого не знає, і це навмисно (портованість, розділ 3
плану, частина C).

Головне, що перевіряється, -- не розбір JSON, а рішення «ретраїти чи ні»:
Meta віддає 400 і на вичерпану квоту, і на протухлий токен, тож помилка
класифікації коштує або втрачених лідів, або черги, що вічно б'ється в
мертвий токен.
"""
import hashlib
import hmac
import json

import pytest

import app.services.meta_graph_client as mgc
from app.services.meta_contracts import (
    LEAD_FIELDS,
    RETRYABLE_ERROR_CODES,
    TOKEN_ERROR_CODE,
)
from app.services.meta_graph_client import MetaConfigError, MetaGraphClient
from tests.support.fake_meta_graph import (
    FakeMetaGraphClient,
    make_field_data,
    make_lead,
)

APP_ID = '1234567890'
APP_SECRET = 'app-secret'
PAGE_TOKEN = 'page-token'


class _FakeResp:
    def __init__(self, status=200, data=None, text=''):
        self.status_code = status
        self._data = data
        self.ok = 200 <= status < 300
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError('no json')
        return self._data


class _Recorder:
    """Підміна `requests.request`: віддає заготовлені відповіді по черзі."""

    def __init__(self, responses):
        #: елемент -- або _FakeResp, або виняток, який треба підняти
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, params=None, data=None, headers=None, timeout=None):
        self.calls.append({
            'method': method, 'url': url, 'params': params,
            'data': data, 'timeout': timeout,
        })
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def _client(**kwargs):
    kwargs.setdefault('app_id', APP_ID)
    kwargs.setdefault('app_secret', APP_SECRET)
    kwargs.setdefault('access_token', PAGE_TOKEN)
    return MetaGraphClient(**kwargs)


def _install(monkeypatch, *responses):
    recorder = _Recorder(responses)
    monkeypatch.setattr(mgc.requests, 'request', recorder)
    return recorder


def _meta_error(code, message='boom', http_status=400, err_type='OAuthException'):
    return _FakeResp(http_status, {'error': {
        'message': message, 'type': err_type, 'code': code,
        'fbtrace_id': 'Atrace123',
    }})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(mgc.time, 'sleep', lambda *_a, **_k: None)


class _Settings:
    """Мінімальний носій налаштувань -- клієнту байдуже, що це не модель."""
    meta_leads_enabled = True
    meta_app_id = APP_ID
    meta_app_secret = APP_SECRET
    meta_page_token = PAGE_TOKEN
    meta_graph_version = 'v22.0'


# ----------------------------- конфігурація -----------------------------

def test_from_settings_builds_client():
    client = MetaGraphClient.from_settings(_Settings())
    assert client.app_id == APP_ID
    assert client.access_token == PAGE_TOKEN
    assert client.version == 'v22.0'


def test_from_settings_falls_back_to_contract_version():
    class S(_Settings):
        meta_graph_version = ''
    assert MetaGraphClient.from_settings(S()).version == mgc.DEFAULT_GRAPH_VERSION


def test_from_settings_rejects_disabled_integration():
    class S(_Settings):
        meta_leads_enabled = False
    with pytest.raises(MetaConfigError):
        MetaGraphClient.from_settings(S())


@pytest.mark.parametrize('field', [
    'meta_app_id', 'meta_app_secret', 'meta_page_token',
])
def test_from_settings_requires_credentials(field):
    class S(_Settings):
        pass
    setattr(S, field, '')
    with pytest.raises(MetaConfigError):
        MetaGraphClient.from_settings(S())


def test_from_settings_allows_missing_token_for_initial_setup():
    """Кнопка обміну токенів працює ДО того, як Page token з'явився."""
    class S(_Settings):
        meta_page_token = ''
    client = MetaGraphClient.from_settings(S(), require_token=False)
    assert client.access_token == ''


# ----------------------------- отримання ліда -----------------------------

def test_get_lead_returns_full_payload(monkeypatch):
    lead = make_lead('1000000000000001')
    recorder = _install(monkeypatch, _FakeResp(200, lead))

    result = _client().get_lead('1000000000000001')

    assert result.ok is True
    assert result.http_status == 200
    assert result.data['campaign_name'] == 'PRP серпень'
    # field_data приходить списком {name, values}, а не dict -- саме в
    # цьому форматі його чекає нормалізація.
    names = [f['name'] for f in result.data['field_data']]
    assert names == ['full_name', 'email', 'phone_number']
    assert result.data['field_data'][1]['values'] == ['olena@example.com']

    call = recorder.calls[0]
    assert call['method'] == 'GET'
    assert call['url'].endswith('/v21.0/1000000000000001')
    assert call['params']['fields'] == ','.join(LEAD_FIELDS)
    assert call['timeout'] == mgc.TIMEOUT


def test_get_lead_parses_custom_field_data(monkeypatch):
    lead = make_lead('7', field_data=make_field_data(email='a@b.co', місто='Київ'))
    _install(monkeypatch, _FakeResp(200, lead))

    result = _client().get_lead('7')

    assert result.data['field_data'][-1] == {'name': 'місто', 'values': ['Київ']}


def test_version_comes_from_settings(monkeypatch):
    """Meta виводить версії з ужитку за розкладом -- шлях бере self.version."""
    recorder = _install(monkeypatch, _FakeResp(200, make_lead('7')))

    _client(version='v22.0').get_lead('7')

    assert '/v22.0/7' in recorder.calls[0]['url']


# ----------------------------- appsecret_proof -----------------------------

def _expected_proof(token):
    return hmac.new(APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()


def test_appsecret_proof_is_sent_with_every_call(monkeypatch):
    """Без профа застосунок із «Require App Secret Proof» відхиляє все."""
    recorder = _install(monkeypatch, _FakeResp(200, {'data': [], 'paging': {}}))
    client = _client()

    client.get_lead('7')
    client.list_form_leads('99')
    client.list_page_forms('555')
    client.subscribe_page('555')

    assert len(recorder.calls) == 4
    for call in recorder.calls:
        assert call['params']['access_token'] == PAGE_TOKEN
        assert call['params']['appsecret_proof'] == _expected_proof(PAGE_TOKEN)


def test_proof_matches_the_token_actually_used(monkeypatch):
    """У get_page_token ходимо під User token -- проф має бути його."""
    recorder = _install(monkeypatch, _FakeResp(200, {'id': '555', 'access_token': 'p'}))

    _client().get_page_token('555', 'user-token')

    params = recorder.calls[0]['params']
    assert params['access_token'] == 'user-token'
    assert params['appsecret_proof'] == _expected_proof('user-token')


def test_proof_is_skipped_without_app_secret(monkeypatch):
    recorder = _install(monkeypatch, _FakeResp(200, make_lead('7')))

    _client(app_secret='').get_lead('7')

    assert 'appsecret_proof' not in recorder.calls[0]['params']


# ----------------------------- класифікація помилок -----------------------------

def test_error_codes_come_from_the_shared_contract():
    """Ні клієнт, ні фейк не мають тримати власної копії переліку.

    Перевірка саме на тотожність об'єкта, а не на рівність: копія-літерал,
    дописана в клієнт «щоб не імпортувати», рівність пройде і розійдеться з
    контрактом мовчки -- на першому ж новому коді помилки.
    """
    assert mgc.RETRYABLE_ERROR_CODES is RETRYABLE_ERROR_CODES
    assert FakeMetaGraphClient.RETRYABLE_CODES is RETRYABLE_ERROR_CODES
    assert mgc.TOKEN_ERROR_CODE == TOKEN_ERROR_CODE == FakeMetaGraphClient.TOKEN_ERROR_CODE


def test_server_error_is_retried_to_the_limit(monkeypatch):
    recorder = _install(monkeypatch, _FakeResp(503, None, text='bad gateway'))

    result = _client().get_lead('7')

    assert result.ok is False
    assert result.retryable is True
    assert result.http_status == 503
    assert len(recorder.calls) == mgc._MAX_ATTEMPTS


def test_timeout_is_retried_to_the_limit(monkeypatch):
    recorder = _install(monkeypatch, mgc.requests.Timeout('read timed out'))

    result = _client().get_lead('7')

    assert result.ok is False
    assert result.retryable is True
    assert len(recorder.calls) == mgc._MAX_ATTEMPTS


def test_connection_error_never_leaks_the_token(monkeypatch):
    """Текст винятку requests несе повний URL -- разом із токеном."""
    boom = mgc.requests.ConnectionError(
        'Max retries exceeded with url: /v21.0/7?access_token=page-token&x=1'
    )
    _install(monkeypatch, boom)

    result = _client().get_lead('7')

    assert PAGE_TOKEN not in (result.error or '')
    assert '<hidden>' in result.error


@pytest.mark.parametrize('code', RETRYABLE_ERROR_CODES)
def test_transient_meta_codes_are_retried(monkeypatch, code):
    """Квоти й тимчасові збої Meta минають самі -- повтор має сенс."""
    recorder = _install(monkeypatch, _meta_error(code, 'rate limited'))

    result = _client().get_lead('7')

    assert result.retryable is True
    assert len(recorder.calls) == mgc._MAX_ATTEMPTS


def test_retry_succeeds_after_transient_failure(monkeypatch):
    recorder = _install(
        monkeypatch,
        _meta_error(RETRYABLE_ERROR_CODES[1], 'service temporarily unavailable'),
        _FakeResp(200, make_lead('7')),
    )

    result = _client().get_lead('7')

    assert result.ok is True
    assert len(recorder.calls) == 2


def test_expired_token_is_not_retried(monkeypatch):
    """code=190 -- діагноз, а не збій: потрібна ротація токена руками."""
    recorder = _install(monkeypatch, _meta_error(
        TOKEN_ERROR_CODE, 'Session has expired',
    ))

    result = _client().get_lead('7')

    assert result.ok is False
    assert result.retryable is False
    assert len(recorder.calls) == 1
    assert 'code=190' in result.error
    assert 'Session has expired' in result.error


def test_error_text_carries_code_and_trace(monkeypatch):
    _install(monkeypatch, _meta_error(100, 'Unsupported get request'))

    result = _client().get_lead('7')

    assert result.retryable is False
    assert 'Meta 400' in result.error
    assert 'fbtrace Atrace123' in result.error


def test_unparsable_body_falls_back_to_http_status(monkeypatch):
    _install(monkeypatch, _FakeResp(404, None, text='<html>not found</html>'))

    result = _client().get_lead('7')

    assert result.ok is False
    assert result.retryable is False
    assert 'Meta 404' in result.error


# ----------------------------- пагінація -----------------------------

def _page(rows, next_url=None):
    payload = {'data': rows}
    if next_url:
        payload['paging'] = {'next': next_url}
    return _FakeResp(200, payload)


def test_list_form_leads_collects_all_pages(monkeypatch):
    recorder = _install(
        monkeypatch,
        _page([make_lead('1')], next_url='https://graph.facebook.com/next-1'),
        _page([make_lead('2')], next_url='https://graph.facebook.com/next-2'),
        _page([make_lead('3')]),
    )

    result = _client().list_form_leads('9988776655', since_ts=1755511000, limit=1)

    assert result.ok is True
    assert [row['id'] for row in result.data] == ['1', '2', '3']
    assert len(recorder.calls) == 3
    # Курсор уже несе токен і проф -- дописувати параметри не можна.
    assert recorder.calls[1]['url'] == 'https://graph.facebook.com/next-1'
    assert recorder.calls[1]['params'] is None


def test_list_form_leads_asks_meta_to_filter_by_time(monkeypatch):
    recorder = _install(monkeypatch, _page([]))

    _client().list_form_leads('9988776655', since_ts=1755511000, limit=50)

    params = recorder.calls[0]['params']
    assert params['limit'] == '50'
    assert json.loads(params['filtering']) == [{
        'field': 'time_created', 'operator': 'GREATER_THAN', 'value': 1755511000,
    }]


def test_list_form_leads_without_since_sends_no_filter(monkeypatch):
    recorder = _install(monkeypatch, _page([]))

    _client().list_form_leads('9988776655')

    assert 'filtering' not in recorder.calls[0]['params']


def test_pagination_stops_at_the_page_cap(monkeypatch):
    """Курсор на ту саму сторінку не має крутити цикл вічно."""
    monkeypatch.setattr(mgc, '_MAX_PAGES', 2)
    recorder = _install(
        monkeypatch,
        _page([make_lead('1')], next_url='https://graph.facebook.com/loop'),
    )

    result = _client().list_form_leads('9988776655')

    assert result.ok is True
    assert len(recorder.calls) == 2
    assert len(result.data) == 2


def test_pagination_returns_failure_of_a_later_page(monkeypatch):
    _install(
        monkeypatch,
        _page([make_lead('1')], next_url='https://graph.facebook.com/next-1'),
        _meta_error(TOKEN_ERROR_CODE, 'Session has expired'),
    )

    result = _client().list_form_leads('9988776655')

    assert result.ok is False
    assert result.retryable is False


def test_list_page_forms_returns_flat_list(monkeypatch):
    forms = [{'id': '9988776655', 'name': 'Плазмотерапія', 'status': 'ACTIVE'}]
    recorder = _install(monkeypatch, _page(forms))

    result = _client().list_page_forms('555000111')

    assert result.data == forms
    assert recorder.calls[0]['url'].endswith('/v21.0/555000111/leadgen_forms')


# ----------------------------- токен і підписка -----------------------------

def test_debug_token_unwraps_payload_and_uses_app_token(monkeypatch):
    recorder = _install(monkeypatch, _FakeResp(200, {'data': {
        'is_valid': True, 'expires_at': 0, 'scopes': ['leads_retrieval'],
    }}))

    result = _client().debug_token()

    assert result.data['is_valid'] is True
    assert result.data['expires_at'] == 0
    params = recorder.calls[0]['params']
    assert params['input_token'] == PAGE_TOKEN
    assert params['access_token'] == f'{APP_ID}|{APP_SECRET}'
    # Секрет уже всередині App Access Token, окремий проф не потрібен.
    assert 'appsecret_proof' not in params


def test_exchange_long_lived_user_token(monkeypatch):
    recorder = _install(monkeypatch, _FakeResp(200, {
        'access_token': 'long-token', 'expires_in': 5184000,
    }))

    result = _client().exchange_long_lived_user_token('short-token')

    assert result.data['access_token'] == 'long-token'
    params = recorder.calls[0]['params']
    assert params['grant_type'] == 'fb_exchange_token'
    assert params['fb_exchange_token'] == 'short-token'
    assert params['client_id'] == APP_ID


def test_subscribe_page_posts_leadgen_field(monkeypatch):
    recorder = _install(monkeypatch, _FakeResp(200, {'success': True}))

    result = _client().subscribe_page('555000111')

    assert result.ok is True
    call = recorder.calls[0]
    assert call['method'] == 'POST'
    assert call['url'].endswith('/v21.0/555000111/subscribed_apps')
    assert call['data'] == {'subscribed_fields': 'leadgen'}
