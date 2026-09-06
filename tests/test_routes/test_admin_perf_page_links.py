"""Фільтр `verdict` на сторінках ОДНОГО перф-прогону (`perf_run_detail`) --
раніше pages_warn/pages_fail не мали куди вести, бо звузити таблицю
сторінок було нічим. Тепер є `verdict`-фільтр, і два місця посилаються на
нього: картки-лічильники на самій сторінці деталей і клітинки pages_warn/
pages_fail у реєстрі прогонів (perf_runs.html).

Це ІНШИЙ рівень зрізу, ніж `verdict` у списку прогонів (`test_admin_spot_
links.py::test_perf_run_verdict_links_to_perf_runs_filtered_by_verdict`):
той фільтрує РЯДКИ /admin/perf (прогони), цей -- СТОРІНКИ одного прогону.
"""
from tests.support.rbac import grant_role
import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from flask import url_for

from app.extensions import db
from app.models.perf_run import PerfPageMetric, PerfRun, VERDICT_FAIL, VERDICT_OK, VERDICT_WARN
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'ppl-{_uid()}@test.com', 'password123',
        first_name='P', last_name='L', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _page(run_id, profile, path, verdict):
    return PerfPageMetric(
        run_id=run_id, profile=profile, path=path, url=f'https://iprm.space{path}',
        status=200, ttfb=100, fcp=200, lcp=300, tbt=0, load_ms=400, cls=0.0,
        total_transfer=1000, req_count=5, verdict=verdict,
    )


@pytest.fixture
def run_with_pages(app):
    """Один прогін, три сторінки: OK, WARN і FAIL -- по одній кожного
    вердикту, обидва профілі присутні, щоб перевірити й звуження, і
    незмінність без фільтра одним і тим самим набором даних."""
    note = f'ppl-{_uid()}'
    run = PerfRun(
        measured_at=datetime.now(timezone.utc), base_url='https://iprm.space',
        source='ppl-test', note=note, verdict=VERDICT_FAIL,
        pages_total=3, pages_warn=1, pages_fail=1,
    )
    db.session.add(run)
    db.session.flush()
    db.session.add(_page(run.id, 'desktop', '/', VERDICT_OK))
    db.session.add(_page(run.id, 'desktop', '/warn', VERDICT_WARN))
    db.session.add(_page(run.id, 'mobile', '/fail', VERDICT_FAIL))
    db.session.commit()
    yield run
    db.session.rollback()
    db.session.delete(db.session.merge(run))
    db.session.commit()


@pytest.fixture
def run_all_ok(app):
    """Прогін без жодного WARN/FAIL -- обидва лічильники нульові, обидві
    клітинки мусять лишитись голим текстом."""
    note = f'ppl-ok-{_uid()}'
    run = PerfRun(
        measured_at=datetime.now(timezone.utc), base_url='https://iprm.space',
        source='ppl-test', note=note, verdict=VERDICT_OK,
        pages_total=1, pages_warn=0, pages_fail=0,
    )
    db.session.add(run)
    db.session.flush()
    db.session.add(_page(run.id, 'desktop', '/', VERDICT_OK))
    db.session.commit()
    yield run
    db.session.rollback()
    db.session.delete(db.session.merge(run))
    db.session.commit()


def test_no_verdict_param_renders_all_three_pages(client, admin, run_with_pages):
    """Без ?verdict -- усі три сторінки на місці, як і до фільтра."""
    _login(client, admin)
    html = client.get(f'/admin/perf/{run_with_pages.id}').get_data(as_text=True)
    assert html.count('<strong>/</strong>') == 1
    assert html.count('<strong>/warn</strong>') == 1
    assert html.count('<strong>/fail</strong>') == 1


def test_verdict_param_narrows_pages_to_that_verdict(client, admin, run_with_pages):
    """?verdict=WARN лишає лише сторінку з цим вердиктом -- OK і FAIL зникають
    з таблиці."""
    _login(client, admin)
    html = client.get(f'/admin/perf/{run_with_pages.id}?verdict=WARN').get_data(as_text=True)
    assert '<strong>/warn</strong>' in html
    assert '<strong>/</strong>' not in html
    assert '<strong>/fail</strong>' not in html


def test_filtered_page_offers_plain_way_back_to_unfiltered(client, admin, run_with_pages):
    """Під фільтром має бути очевидно, що показано не все, і як повернутись."""
    _login(client, admin)
    html = client.get(f'/admin/perf/{run_with_pages.id}?verdict=FAIL').get_data(as_text=True)
    with client.application.test_request_context():
        back_href = url_for('admin.perf_run_detail', run_id=run_with_pages.id)
    assert re.search(rf'<a href="{re.escape(back_href)}">', html)


def test_stat_cards_link_to_filtered_page_with_right_verdict(client, admin, run_with_pages):
    """Обидві картки WARN/FAIL ведуть у ЦЕЙ САМИЙ прогін, звужений своїм
    вердиктом -- від значення до тега, як вимагає сторож «тег навколо
    значення»."""
    _login(client, admin)
    html = client.get(f'/admin/perf/{run_with_pages.id}').get_data(as_text=True)
    with client.application.test_request_context():
        warn_href = url_for('admin.perf_run_detail', run_id=run_with_pages.id, verdict='WARN')
        fail_href = url_for('admin.perf_run_detail', run_id=run_with_pages.id, verdict='FAIL')
    assert re.search(
        rf'<a[^>]*class="[^"]*admin-stat-card[^"]*"[^>]*href="{re.escape(warn_href)}"[^>]*>\s*'
        rf'<div class="admin-stat-card__value">{run_with_pages.pages_warn}</div>',
        html,
    )
    assert re.search(
        rf'<a[^>]*class="[^"]*admin-stat-card[^"]*"[^>]*href="{re.escape(fail_href)}"[^>]*>\s*'
        rf'<div class="admin-stat-card__value">{run_with_pages.pages_fail}</div>',
        html,
    )


def test_zero_stat_cards_stay_plain_text(client, admin, run_all_ok):
    """pages_warn і pages_fail дорівнюють нулю -- обидві картки лишаються
    <div>, жодного <a> навколо нуля."""
    _login(client, admin)
    html = client.get(f'/admin/perf/{run_all_ok.id}').get_data(as_text=True)
    assert not re.search(
        r'<a[^>]*class="[^"]*admin-stat-card[^"]*"[^>]*>\s*<div class="admin-stat-card__value">0</div>',
        html,
    )
    assert re.search(
        r'<div class="admin-stat-card admin-stat-card--alert">\s*'
        r'<div class="admin-stat-card__value">0</div>',
        html,
    )
    assert re.search(
        r'<div class="admin-stat-card admin-stat-card--danger">\s*'
        r'<div class="admin-stat-card__value">0</div>',
        html,
    )


def test_runs_list_cells_link_to_run_detail_with_verdict(client, admin, run_with_pages):
    """Реєстр прогонів (`perf_runs.html`): клітинки pages_warn/pages_fail
    ведуть у ДЕТАЛІ цього прогону зі своїм вердиктом -- не плутати з
    посиланням на самому вердикті рядка, що веде у СПИСОК ПРОГОНІВ."""
    _login(client, admin)
    html = client.get(f'/admin/perf?q={run_with_pages.note}').get_data(as_text=True)
    with client.application.test_request_context():
        warn_href = url_for('admin.perf_run_detail', run_id=run_with_pages.id, verdict='WARN')
        fail_href = url_for('admin.perf_run_detail', run_id=run_with_pages.id, verdict='FAIL')
    assert re.search(
        rf'<a href="{re.escape(warn_href)}">\s*{run_with_pages.pages_warn}\s*</a>', html,
    )
    assert re.search(
        rf'<a href="{re.escape(fail_href)}">\s*{run_with_pages.pages_fail}\s*</a>', html,
    )


def test_latest_run_hero_cards_link_with_verdict(client, admin, run_with_pages):
    """Верхні картки «Останній замір» на /admin/perf (perf_runs.html) --
    та сама розмітка й та сама ціль, що й картки на perf_run_detail: клік
    веде в ДЕТАЛІ цього прогону, звужені фільтром сторінок за вердиктом.
    Тест ізольований (rollback per-test), тож `run_with_pages` тут і є
    єдиним прогоном -- саме він і стане `latest`."""
    _login(client, admin)
    html = client.get('/admin/perf').get_data(as_text=True)
    with client.application.test_request_context():
        warn_href = url_for('admin.perf_run_detail', run_id=run_with_pages.id, verdict='WARN')
        fail_href = url_for('admin.perf_run_detail', run_id=run_with_pages.id, verdict='FAIL')
    assert re.search(
        rf'<a[^>]*class="[^"]*admin-stat-card[^"]*"[^>]*href="{re.escape(warn_href)}"[^>]*>\s*'
        rf'<div class="admin-stat-card__value">{run_with_pages.pages_warn}</div>',
        html,
    )
    assert re.search(
        rf'<a[^>]*class="[^"]*admin-stat-card[^"]*"[^>]*href="{re.escape(fail_href)}"[^>]*>\s*'
        rf'<div class="admin-stat-card__value">{run_with_pages.pages_fail}</div>',
        html,
    )


def test_latest_run_hero_cards_stay_plain_text_when_zero(client, admin, run_all_ok):
    """Той самий блок, прогін без жодного WARN/FAIL -- обидві картки
    лишаються <div>, жодного <a> навколо нуля."""
    _login(client, admin)
    html = client.get('/admin/perf').get_data(as_text=True)
    assert not re.search(
        r'<a[^>]*class="[^"]*admin-stat-card[^"]*"[^>]*>\s*<div class="admin-stat-card__value">0</div>',
        html,
    )
    assert re.search(
        r'<div class="admin-stat-card admin-stat-card--alert">\s*'
        r'<div class="admin-stat-card__value">0</div>',
        html,
    )
    assert re.search(
        r'<div class="admin-stat-card admin-stat-card--danger">\s*'
        r'<div class="admin-stat-card__value">0</div>',
        html,
    )


def test_runs_list_zero_counts_stay_plain_text(client, admin, run_all_ok):
    """Той самий реєстр, прогін без жодного WARN/FAIL -- обидві клітинки
    лишаються голим "0", без <a> навколо. Якір -- pages_total (1) цього
    прогону: наступні два <td> і є warn/fail."""
    _login(client, admin)
    html = client.get(f'/admin/perf?q={run_all_ok.note}').get_data(as_text=True)
    match = re.search(
        rf'<td>{run_all_ok.pages_total}</td>\s*<td>(\d+)</td>\s*<td>(\d+)</td>',
        html,
    )
    assert match, 'рядок прогону з лічильниками не знайдено'
    assert match.group(1) == '0'
    assert match.group(2) == '0'
