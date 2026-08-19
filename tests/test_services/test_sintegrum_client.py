"""Тести клієнта API Sintegrum.

Мережі тут немає: requests.request підмінюється, sleep -- теж, інакше
ретраї перетворили б набір на секунди очікування. Бази теж немає --
клієнт про неї нічого не знає, і це навмисно (портованість, Р7 плану).
"""
import pytest

import app.services.sintegrum_client as sc
from app.services.sintegrum_client import SintegrumClient, SintegrumConfigError


class _FakeResp:
    def __init__(self, status, data, text=''):
        self.status_code = status
        self._data = data
        self.ok = 200 <= status < 300
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError('no json')
        return self._data


class _Settings:
    """Мінімальний носій налаштувань -- клієнту байдуже, що це не модель."""
    sintegrum_enabled = True
    sintegrum_api_base_url = 'https://api.sintegrum.com'
    sintegrum_company_alias = 'multimededu'
    sintegrum_api_key = 'secret-key'


def _course(course_id, name='Курс', **extra):
    data = {'id': course_id, 'name': name, 'status': 1, 'price': 1000}
    data.update(extra)
    return data


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(sc.time, 'sleep', lambda *_a, **_k: None)


# ----------------------------- конфігурація -----------------------------

def test_from_settings_builds_client():
    client = SintegrumClient.from_settings(_Settings())
    assert client.company == 'multimededu'
    assert client.base_url == 'https://api.sintegrum.com'


def test_from_settings_rejects_disabled_integration():
    class S(_Settings):
        sintegrum_enabled = False
    with pytest.raises(SintegrumConfigError):
        SintegrumClient.from_settings(S())


@pytest.mark.parametrize('field', [
    'sintegrum_api_base_url', 'sintegrum_company_alias', 'sintegrum_api_key',
])
def test_from_settings_requires_every_field(field):
    class S(_Settings):
        pass
    setattr(S, field, '')
    with pytest.raises(SintegrumConfigError):
        SintegrumClient.from_settings(S())


def test_base_url_trailing_slash_does_not_double(monkeypatch):
    seen = {}

    def fake_request(method, url, **kw):
        seen['url'] = url
        return _FakeResp(200, [])

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    SintegrumClient('https://api.sintegrum.com/', 'acme', 'k').get_config()
    assert seen['url'] == 'https://api.sintegrum.com/external/acme/config'


# ----------------------------- транспорт -----------------------------

def test_bearer_header_is_sent(monkeypatch):
    seen = {}

    def fake_request(method, url, headers=None, **kw):
        seen['headers'] = headers
        return _FakeResp(200, [])

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    SintegrumClient('https://x', 'acme', 'my-key').get_config()
    assert seen['headers']['Authorization'] == 'Bearer my-key'


def test_retries_on_connection_error_then_succeeds(monkeypatch):
    calls = {'n': 0}

    def fake_request(method, url, **kw):
        calls['n'] += 1
        if calls['n'] < 3:
            raise sc.requests.ConnectionError('boom')
        return _FakeResp(200, [])

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').get_config()
    assert result.ok is True
    assert calls['n'] == 3


def test_retries_exhausted_returns_error(monkeypatch):
    def fake_request(method, url, **kw):
        raise sc.requests.Timeout('slow')

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').get_config()
    assert result.ok is False
    assert 'зв' in result.error


def test_server_error_is_retried(monkeypatch):
    calls = {'n': 0}

    def fake_request(method, url, **kw):
        calls['n'] += 1
        return _FakeResp(503, None, text='gateway')

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').get_config()
    assert result.ok is False
    assert calls['n'] == 3
    assert result.http_status == 503


def test_unauthorized_is_permanent_and_not_retried(monkeypatch):
    calls = {'n': 0}

    def fake_request(method, url, **kw):
        calls['n'] += 1
        return _FakeResp(401, {'message': 'Your request was made with invalid credentials.'})

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'bad').get_config()
    assert result.ok is False
    assert calls['n'] == 1
    assert '401' in result.error


def test_error_text_never_leaks_the_api_key(monkeypatch):
    def fake_request(method, url, **kw):
        return _FakeResp(403, {'message': 'forbidden'})

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'super-secret-key').get_config()
    assert 'super-secret-key' not in (result.error or '')


def test_non_json_response_does_not_crash(monkeypatch):
    def fake_request(method, url, **kw):
        return _FakeResp(200, None)

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').get_config()
    assert result.ok is True
    assert result.data is None


# ----------------------------- пагінація каталогу -----------------------------

def test_list_all_courses_walks_pages(monkeypatch):
    pages = {
        '1': [_course(i) for i in range(1, 101)],
        '2': [_course(i) for i in range(101, 151)],
    }
    seen_pages = []

    def fake_request(method, url, **kw):
        page = url.split('page=')[1].split('&')[0]
        seen_pages.append(page)
        return _FakeResp(200, pages.get(page, []))

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').list_all_courses()
    assert result.ok is True
    assert len(result.data) == 150
    # Друга сторінка коротша за per-page -- третьої вже не питаємо.
    assert seen_pages == ['1', '2']


def test_list_all_courses_stops_on_empty_page(monkeypatch):
    calls = {'n': 0}

    def fake_request(method, url, **kw):
        calls['n'] += 1
        return _FakeResp(200, [_course(i) for i in range(1, 101)] if calls['n'] == 1 else [])

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').list_all_courses()
    assert len(result.data) == 100
    assert calls['n'] == 2


def test_list_all_courses_stops_when_page_repeats(monkeypatch):
    """Захист від нескінченного циклу, якщо пагінація на тому боці зламана."""
    def fake_request(method, url, **kw):
        return _FakeResp(200, [_course(i) for i in range(1, 101)])

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').list_all_courses()
    assert result.ok is True
    assert len(result.data) == 100


def test_list_all_courses_propagates_failure(monkeypatch):
    def fake_request(method, url, **kw):
        return _FakeResp(401, {'message': 'nope'})

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').list_all_courses()
    assert result.ok is False
    assert result.http_status == 401
    # data несе тіло помилки (воно потрібне адмінці), але не список курсів --
    # інакше синхронізація прийняла б помилку за порожній каталог.
    assert not isinstance(result.data, list)


def test_partial_failure_does_not_return_half_a_catalog(monkeypatch):
    """Друга сторінка впала -- віддаємо помилку, а не обрізаний каталог.

    Інакше синхронізація вирішила б, що решти курсів більше не існує,
    і позначила б їх зниклими.
    """
    calls = {'n': 0}

    def fake_request(method, url, **kw):
        calls['n'] += 1
        if calls['n'] == 1:
            return _FakeResp(200, [_course(i) for i in range(1, 101)])
        return _FakeResp(500, None)

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').list_all_courses()
    assert result.ok is False


# ----------------------------- ping і учні -----------------------------

def test_ping_uses_cheapest_call(monkeypatch):
    seen = {}

    def fake_request(method, url, **kw):
        seen['url'] = url
        return _FakeResp(200, [])

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').ping()
    assert result.ok is True
    assert 'per-page=1' in seen['url']
    assert '/course' in seen['url']


def test_ping_rejects_unexpected_payload_shape(monkeypatch):
    def fake_request(method, url, **kw):
        return _FakeResp(200, {'unexpected': True})

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').ping()
    assert result.ok is False


def test_create_student_sends_expected_payload(monkeypatch):
    seen = {}

    def fake_request(method, url, json=None, **kw):
        seen['method'] = method
        seen['url'] = url
        seen['json'] = json
        return _FakeResp(201, {'id': 7, 'email': 'a@b.c'})

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').create_student(
        email='a@b.c', first_name='Ольга', last_name='Коваль', language='uk',
    )
    assert result.ok is True
    assert seen['method'] == 'POST'
    assert seen['url'].endswith('/external/acme/student')
    assert seen['json']['email'] == 'a@b.c'
    # Порожні поля не відправляємо -- Sintegrum трактує їх як явне затирання.
    assert 'phone' not in seen['json']


def test_list_students_passes_filter(monkeypatch):
    """Фільтр іде окремими параметрами, а не рядком у параметрі `filter`.

    Раніше запит виглядав як `?filter=filter[email][eq]=...`: назва
    параметра дублювалась у власному значенні, тож партнер фільтр
    ігнорував, і пошук учня за email мовчки не працював.
    """
    from urllib.parse import parse_qs, urlparse

    seen = {}

    def fake_request(method, url, **kw):
        seen['url'] = url
        return _FakeResp(200, [])

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    SintegrumClient('https://x', 'acme', 'k').list_students(
        filters={'filter[email][eq]': 'a@b.c'},
    )

    query = parse_qs(urlparse(seen['url']).query)
    assert query['filter[email][eq]'] == ['a@b.c']
    assert 'filter' not in query


def test_find_student_filters_by_email(monkeypatch):
    seen = {}

    def fake_request(method, url, **kw):
        seen['url'] = url
        return _FakeResp(200, [{'id': 7, 'email': 'a@b.c'}])

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').find_student_by_email('a@b.c')

    assert result.ok is True
    assert result.data['id'] == 7
    assert 'filter%5Bemail%5D%5Beq%5D=a%40b.c' in seen['url']


def test_find_student_ignores_someone_else(monkeypatch):
    """Відповідь, яку не відфільтрували, не має видати чужого учня за свого."""
    def fake_request(method, url, **kw):
        return _FakeResp(200, [{'id': 1, 'email': 'other@example.com'}])

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').find_student_by_email('a@b.c')

    assert result.ok is True
    assert result.data is None


# ----------------------------- ретраї -----------------------------

def test_post_is_not_retried_after_read_timeout(monkeypatch):
    """POST /student не ідемпотентний: повтор завів би другого учня.

    Таймаут ЧИТАННЯ означає, що запит уже поїхав і на тому боці міг
    виконатись -- на відміну від невдалого з'єднання.
    """
    calls = []

    def fake_request(method, url, **kw):
        calls.append(method)
        raise sc.requests.ReadTimeout('too slow')

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    result = SintegrumClient('https://x', 'acme', 'k').create_student('a@b.c')

    assert result.ok is False
    assert len(calls) == 1


def test_post_is_retried_when_connection_never_opened(monkeypatch):
    calls = []

    def fake_request(method, url, **kw):
        calls.append(method)
        raise sc.requests.ConnectTimeout('no route')

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    monkeypatch.setattr(sc.time, 'sleep', lambda *a: None)
    result = SintegrumClient('https://x', 'acme', 'k').create_student('a@b.c')

    assert result.ok is False
    assert len(calls) == sc._MAX_ATTEMPTS


def test_post_is_not_retried_on_server_error(monkeypatch):
    calls = []

    def fake_request(method, url, **kw):
        calls.append(method)
        return _FakeResp(500, None)

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    monkeypatch.setattr(sc.time, 'sleep', lambda *a: None)
    result = SintegrumClient('https://x', 'acme', 'k').assign_course(1, 2)

    assert result.ok is False
    assert len(calls) == 1


def test_get_is_still_retried_on_server_error(monkeypatch):
    calls = []

    def fake_request(method, url, **kw):
        calls.append(method)
        return _FakeResp(500, None)

    monkeypatch.setattr(sc.requests, 'request', fake_request)
    monkeypatch.setattr(sc.time, 'sleep', lambda *a: None)
    SintegrumClient('https://x', 'acme', 'k').list_courses_page()

    assert len(calls) == sc._MAX_ATTEMPTS


# ----------------------------- health-check -----------------------------

def test_health_check_reports_not_configured_when_disabled():
    from app.services.integration_health import _check_sintegrum, HealthStatus

    class S(_Settings):
        sintegrum_enabled = False

    assert _check_sintegrum(S())['status'] == HealthStatus.NOT_CONFIGURED


def test_health_check_ok(monkeypatch):
    from app.services.integration_health import _check_sintegrum, HealthStatus

    monkeypatch.setattr(sc.requests, 'request', lambda *a, **kw: _FakeResp(200, []))
    result = _check_sintegrum(_Settings())
    assert result['status'] == HealthStatus.OK
    assert 'multimededu' in result['detail']


def test_health_check_bad_key_is_down(monkeypatch):
    from app.services.integration_health import _check_sintegrum, HealthStatus

    monkeypatch.setattr(sc.requests, 'request', lambda *a, **kw: _FakeResp(401, {}))
    result = _check_sintegrum(_Settings())
    assert result['status'] == HealthStatus.DOWN
    assert 'secret-key' not in result['error']
