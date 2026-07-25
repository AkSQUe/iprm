"""Приймання і розбір замірів швидкості від tools/perf/perf_check.py.

Заміри приходять ззовні (машина розробника або CI) у POST /api/v1/perf/runs --
на проді браузер не запускається свідомо, див. докстрінг app/models/perf_run.py.
Тут -- валідація payload-а, збереження і порівняння прогонів між собою.
"""
import logging
from datetime import datetime, timezone

from app.extensions import db
from app.models.perf_run import (
    PerfPageMetric, PerfRun, VERDICTS, VERDICT_OK, VERDICT_WARN, VERDICT_FAIL,
    worst_verdict,
)

logger = logging.getLogger(__name__)

# Скільки прогонів тримаємо. Старші видаляються при кожному прийманні --
# історія потрібна для тренду, а не як архів; кожен прогін тягне за собою
# десятки рядків метрик.
MAX_RUNS = 100

# Стелі проти роздування payload-а недобросовісним/зламаним клієнтом.
MAX_PAGES = 200
MAX_DETAIL_ITEMS = 10

# Дзеркалить REGRESSION_PCT / REGRESSION_ABS у tools/perf/perf_check.py:
# регресія -- це погіршення одночасно у відсотках і в абсолюті, інакше
# коливання каналу читалися б як просідання.
REGRESSION_PCT = 0.20
REGRESSION_ABS = {'lcp': 150, 'tbt': 100, 'total_transfer': 50 * 1024}
COMPARED_METRICS = ('lcp', 'tbt', 'total_transfer')


class PerfIngestError(ValueError):
    """Payload не пройшов валідацію -- відповідаємо 400."""


def _as_int(value, field):
    if value is None or value == '':
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        raise PerfIngestError(f'Поле {field} має бути числом')


def _as_float(value, field):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise PerfIngestError(f'Поле {field} має бути числом')


def _as_text(value, limit):
    if value is None:
        return ''
    return str(value)[:limit]


def _parse_measured_at(raw):
    if not raw:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        raise PerfIngestError('measured_at має бути датою у форматі ISO 8601')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _clean_verdict(raw):
    verdict = str(raw or VERDICT_OK).upper()
    if verdict not in VERDICTS:
        raise PerfIngestError(f'Невідомий вердикт: {verdict}')
    return verdict


def _clean_details(raw):
    """Лишаємо тільки те, що показує UI, і обрізаємо списки до стелі."""
    if not isinstance(raw, dict):
        return {}
    by_type = raw.get('by_type')
    return {
        'by_type': by_type if isinstance(by_type, dict) else {},
        'heaviest': list(raw.get('heaviest') or [])[:MAX_DETAIL_ITEMS],
        'uncompressed': list(raw.get('uncompressed') or [])[:MAX_DETAIL_ITEMS],
        'headers': raw.get('headers') if isinstance(raw.get('headers'), dict) else {},
    }


def _build_page(raw):
    if not isinstance(raw, dict):
        raise PerfIngestError('Кожен елемент pages має бути обʼєктом')
    profile = _as_text(raw.get('profile'), 20)
    path = _as_text(raw.get('path'), 255)
    if not profile or not path:
        raise PerfIngestError('Кожна сторінка потребує profile і path')

    error = _as_text(raw.get('error'), 255)
    page = PerfPageMetric(
        profile=profile,
        path=path,
        url=_as_text(raw.get('url'), 500),
        status=_as_int(raw.get('status'), 'status'),
        error=error,
    )
    if error:
        # Невиміряна сторінка -- сам факт помилки важливий, метрик немає.
        page.verdict = VERDICT_OK
        page.budget = {}
        page.details = {}
        return page

    page.ttfb = _as_int(raw.get('ttfb'), 'ttfb')
    page.fcp = _as_int(raw.get('fcp'), 'fcp')
    page.lcp = _as_int(raw.get('lcp'), 'lcp')
    page.tbt = _as_int(raw.get('tbt'), 'tbt')
    page.load_ms = _as_int(raw.get('load'), 'load')
    page.cls = _as_float(raw.get('cls'), 'cls')
    page.total_transfer = _as_int(raw.get('total_transfer'), 'total_transfer') or 0
    page.req_count = _as_int(raw.get('req_count'), 'req_count') or 0
    page.doc_transfer = _as_int(raw.get('doc_transfer'), 'doc_transfer') or 0
    page.doc_decoded = _as_int(raw.get('doc_decoded'), 'doc_decoded') or 0
    page.verdict = _clean_verdict(raw.get('verdict'))
    page.budget = raw.get('budget') if isinstance(raw.get('budget'), dict) else {}
    page.details = _clean_details(raw.get('details'))
    return page


def ingest_run(payload):
    """Зберегти прогін із payload-а інструменту. Повертає PerfRun.

    Кидає PerfIngestError на невалідних даних -- ендпоінт перетворює це на 400.
    """
    if not isinstance(payload, dict):
        raise PerfIngestError('Очікується JSON-обʼєкт')

    raw_pages = payload.get('pages')
    if not isinstance(raw_pages, list) or not raw_pages:
        raise PerfIngestError('Поле pages має бути непорожнім списком')
    if len(raw_pages) > MAX_PAGES:
        raise PerfIngestError(f'Забагато сторінок у прогоні (максимум {MAX_PAGES})')

    base_url = _as_text(payload.get('base_url'), 255)
    if not base_url:
        raise PerfIngestError('Поле base_url обовʼязкове')

    budgets = payload.get('budgets')
    run = PerfRun(
        measured_at=_parse_measured_at(payload.get('measured_at')),
        base_url=base_url,
        source=_as_text(payload.get('source'), 100),
        note=_as_text(payload.get('note'), 255),
        runs_per_page=_as_int(payload.get('runs_per_page'), 'runs_per_page') or 0,
        tool_version=_as_text(payload.get('tool_version'), 20),
        budgets=budgets if isinstance(budgets, dict) else {},
    )
    run.pages = [_build_page(p) for p in raw_pages]

    measured = [p for p in run.pages if p.is_measured]
    run.pages_total = len(run.pages)
    run.pages_warn = sum(1 for p in measured if p.verdict == VERDICT_WARN)
    run.pages_fail = sum(1 for p in measured if p.verdict == VERDICT_FAIL)
    run.verdict = worst_verdict([p.verdict for p in measured])

    db.session.add(run)
    db.session.commit()

    _prune_old_runs()
    logger.info(
        'perf: run #%d accepted (%s, %d сторінок, %s)',
        run.id, run.base_url, run.pages_total, run.verdict,
    )
    return run


def _prune_old_runs():
    """Лишити MAX_RUNS найновіших прогонів, старші видалити."""
    ids = [
        row[0] for row in
        db.session.query(PerfRun.id)
        .order_by(PerfRun.measured_at.desc(), PerfRun.id.desc())
        .offset(MAX_RUNS)
        .all()
    ]
    if not ids:
        return
    # ORM-видалення, а не bulk: cascade на perf_page_metrics має відпрацювати
    # і на SQLite, де FK ON DELETE не завжди увімкнено.
    for run in PerfRun.query.filter(PerfRun.id.in_(ids)).all():
        db.session.delete(run)
    db.session.commit()
    logger.info('perf: видалено %d застарілих прогонів', len(ids))


def previous_run(run):
    """Попередній прогін по тому самому base_url -- база для порівняння."""
    return (
        PerfRun.query
        .filter(
            PerfRun.base_url == run.base_url,
            PerfRun.measured_at < run.measured_at,
        )
        .order_by(PerfRun.measured_at.desc(), PerfRun.id.desc())
        .first()
    )


def compare(run, base):
    """Порівняти два прогони посторінково.

    Повертає {"<профіль>:<шлях>": {"<метрика>": {"now", "was", "delta",
    "regressed"}}}. Сторінки, яких немає в базовому прогоні, пропускаються --
    порівнювати нема з чим.
    """
    if base is None:
        return {}
    base_pages = {p.key: p for p in base.pages if p.is_measured}
    result = {}
    for page in run.pages:
        if not page.is_measured:
            continue
        was_page = base_pages.get(page.key)
        if was_page is None:
            continue
        metrics = {}
        for metric in COMPARED_METRICS:
            now = getattr(page, metric, None)
            was = getattr(was_page, metric, None)
            if now is None or was is None:
                continue
            delta = now - was
            regressed = (
                delta > REGRESSION_ABS[metric]
                and was > 0
                and delta / was > REGRESSION_PCT
            )
            metrics[metric] = {
                'now': now, 'was': was, 'delta': delta, 'regressed': regressed,
            }
        if metrics:
            result[page.key] = metrics
    return result


def regression_count(comparison):
    """Скільки метрик просіло у порівнянні -- для бейджа у списку прогонів."""
    return sum(
        1 for metrics in comparison.values()
        for data in metrics.values() if data['regressed']
    )
