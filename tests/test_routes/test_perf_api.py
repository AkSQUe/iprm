"""Tests: приймання замірів швидкості (POST /api/v1/perf/runs) і розбір прогонів.

Заміри робляться поза продом і надсилаються сюди, тож перевіряємо саме
контракт приймання: автентифікацію, валідацію payload-а, зведення вердикту
і порівняння прогонів між собою.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.perf_run import PerfRun
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import perf_service


PERF_KEY = 'test-perf-ingest-key-1234567890123456'
INGEST_URL = '/api/v1/perf/runs'


def _site():
    """Унікальний base_url на тест: conftest не відкочує комміти між тестами,
    тож прогони попередніх тестів лишаються в таблиці і могли б підмінити
    очікуваний "попередній прогін"."""
    return f'https://{uuid4().hex[:8]}.test'


@pytest.fixture
def perf_key(app):
    s = SiteSettings.get()
    s.perf_api_key = PERF_KEY
    db.session.commit()
    yield PERF_KEY
    s.perf_api_key = ''
    db.session.commit()


def _page(profile='mobile', path='/', lcp=1000, tbt=100, verdict='OK', budget=None,
          total_transfer=400 * 1024):
    return {
        'profile': profile,
        'path': path,
        'url': f'https://example.test{path}',
        'status': 200,
        'ttfb': 120,
        'fcp': 900,
        'lcp': lcp,
        'tbt': tbt,
        'cls': 0,
        'load': 3000,
        'total_transfer': total_transfer,
        'req_count': 44,
        'doc_transfer': 6144,
        'doc_decoded': 28672,
        'verdict': verdict,
        'budget': budget or {'lcp': verdict, 'tbt': 'OK', 'cls': 'OK'},
        'details': {
            'by_type': {'script': {'count': 19, 'transfer': 192512}},
            'heaviest': [{'name': 'https://example.test/a.js', 'transfer': 164864, 'dur': 3067}],
            'uncompressed': [],
            'headers': {'content-encoding': 'gzip', 'cache-control': 'no-store'},
        },
    }


def _payload(pages=None, **overrides):
    payload = {
        'measured_at': datetime.now(timezone.utc).isoformat(),
        'base_url': 'https://example.test',
        'source': 'pytest',
        'note': 'базовий замір',
        'runs_per_page': 3,
        'tool_version': '1.0',
        'budgets': {'mobile': {'lcp': [2500, 4000], 'tbt': [200, 600]}},
        'pages': pages if pages is not None else [_page()],
    }
    payload.update(overrides)
    return payload


def test_ingest_disabled_without_key(client, app):
    """Порожній ключ -- ендпоінт не існує (404, а не 401): не підтверджуємо
    наявність приймання тому, хто його намацує."""
    s = SiteSettings.get()
    s.perf_api_key = ''
    db.session.commit()

    resp = client.post(INGEST_URL, json=_payload())
    assert resp.status_code == 404


def test_ingest_rejects_wrong_key(client, perf_key):
    resp = client.post(INGEST_URL, json=_payload(), headers={'X-API-Key': 'wrong'})
    assert resp.status_code == 401


def test_ingest_stores_run_and_pages(client, perf_key):
    pages = [
        _page(profile='mobile', path='/', verdict='OK'),
        _page(profile='mobile', path='/blog/', lcp=2752, verdict='WARN'),
        _page(profile='desktop', path='/', lcp=272, verdict='OK'),
    ]
    resp = client.post(INGEST_URL, json=_payload(pages),
                       headers={'X-API-Key': perf_key})

    assert resp.status_code == 201
    body = resp.get_json()
    # Вердикт прогону -- найгірший серед сторінок.
    assert body['verdict'] == 'WARN'
    assert body['pages_total'] == 3
    assert body['pages_warn'] == 1
    assert body['pages_fail'] == 0

    run = db.session.get(PerfRun, body['id'])
    assert run.base_url == 'https://example.test'
    assert run.source == 'pytest'
    assert len(run.pages) == 3
    assert run.profiles == ['desktop', 'mobile']
    # Межі бюджету зберігаються разом із прогоном, а не беруться з коду.
    assert run.budget_for('mobile', 'lcp') == (2500, 4000)
    # Найповільніша сторінка -- та, з якої починають розбір.
    assert run.worst_page.path == '/blog/'


def test_ingest_verdict_fail_wins(client, perf_key):
    pages = [_page(path='/a', verdict='WARN'), _page(path='/b', verdict='FAIL')]
    resp = client.post(INGEST_URL, json=_payload(pages),
                       headers={'X-API-Key': perf_key})

    body = resp.get_json()
    assert body['verdict'] == 'FAIL'
    assert body['pages_fail'] == 1


def test_ingest_rejects_empty_pages(client, perf_key):
    resp = client.post(INGEST_URL, json=_payload(pages=[]),
                       headers={'X-API-Key': perf_key})
    assert resp.status_code == 400


def test_ingest_rejects_page_without_path(client, perf_key):
    broken = _page()
    del broken['path']
    resp = client.post(INGEST_URL, json=_payload([broken]),
                       headers={'X-API-Key': perf_key})
    assert resp.status_code == 400


def test_unmeasured_page_stored_without_metrics(client, perf_key):
    """Сторінка з помилкою зберігається як факт, але не впливає на вердикт."""
    pages = [_page(), {'profile': 'mobile', 'path': '/down', 'error': 'timeout'}]
    resp = client.post(INGEST_URL, json=_payload(pages),
                       headers={'X-API-Key': perf_key})

    run = db.session.get(PerfRun, resp.get_json()['id'])
    failed = [p for p in run.pages if p.path == '/down'][0]
    assert not failed.is_measured
    assert failed.lcp is None
    assert run.verdict == 'OK'


def test_compare_flags_regression(app):
    """Просідання = гірше і у відсотках, і в абсолюті одночасно."""
    site = _site()
    base = perf_service.ingest_run(_payload(
        [_page(path='/', lcp=1000, tbt=100)], base_url=site,
        measured_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    ))
    current = perf_service.ingest_run(_payload(
        [_page(path='/', lcp=2000, tbt=105)], base_url=site,
    ))

    comparison = perf_service.compare(current, base)
    metrics = comparison['mobile:/']

    assert metrics['lcp']['delta'] == 1000
    assert metrics['lcp']['regressed'] is True
    # +5мс TBT -- у межах шуму каналу, просіданням не вважається.
    assert metrics['tbt']['regressed'] is False
    assert perf_service.regression_count(comparison) == 1


def test_compare_without_baseline_is_empty(app):
    run = perf_service.ingest_run(_payload())
    assert perf_service.compare(run, None) == {}


@pytest.fixture
def admin(app):
    return User.create_with_password(
        f'perf-admin-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_admin_list_renders_with_runs(client, admin):
    perf_service.ingest_run(_payload(base_url=_site()))
    _login(client, admin)

    resp = client.get('/admin/perf')
    assert resp.status_code == 200
    assert 'Швидкість сторінок'.encode() in resp.data
    # Сторінка пояснює, чому заміри не робляться на сервері.
    assert 'perf_check.py'.encode() in resp.data


def test_admin_detail_renders_with_comparison(client, admin):
    site = _site()
    perf_service.ingest_run(_payload(
        [_page(path='/', lcp=1000)], base_url=site,
        measured_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    ))
    current = perf_service.ingest_run(_payload(
        [_page(path='/', lcp=2000, verdict='WARN')], base_url=site,
    ))
    _login(client, admin)

    resp = client.get(f'/admin/perf/{current.id}')
    assert resp.status_code == 200
    assert b'WARN' in resp.data
    # Дельта відносно попереднього прогону показується у клітинці LCP.
    assert '+1000мс'.encode() in resp.data


def test_admin_pages_require_admin(client):
    resp = client.get('/admin/perf')
    assert resp.status_code in (302, 401, 403)


def test_previous_run_matches_same_base_url(app):
    site = _site()
    older = perf_service.ingest_run(_payload(
        base_url=site,
        measured_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    ))
    perf_service.ingest_run(_payload(
        base_url=_site(),
        measured_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    ))
    current = perf_service.ingest_run(_payload(base_url=site))

    # Порівнюємо лише з прогоном того самого сайту -- чужі числа непорівнянні.
    assert perf_service.previous_run(current).id == older.id
