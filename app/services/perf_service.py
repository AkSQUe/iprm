"""Приймання і розбір замірів швидкості від tools/perf/perf_check.py.

Заміри приходять ззовні (машина розробника або CI) у POST /api/v1/perf/runs --
на проді браузер не запускається свідомо, див. докстрінг app/models/perf_run.py.
Тут -- валідація payload-а, збереження і порівняння прогонів між собою.
"""
import logging
import math
from datetime import datetime, timedelta, timezone

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
MAX_TYPE_BUCKETS = 30
MAX_RESOURCE_NAME = 300
# Заголовки документа, які показує UI. Решту не зберігаємо: це і зайва вага
# рядка, і непотрібний слід (Set-Cookie тощо).
KEPT_HEADERS = ('content-encoding', 'cache-control', 'server')

# Годинники вимірювальної машини можуть трохи розходитись із серверними, але
# замір "з майбутнього" назавжди осів би у верхівці списку і зламав би вибір
# попереднього прогону.
MAX_CLOCK_SKEW = timedelta(hours=1)

# Дзеркалить REGRESSION_PCT / REGRESSION_ABS у tools/perf/perf_check.py:
# регресія -- це погіршення одночасно у відсотках і в абсолюті, інакше
# коливання каналу читалися б як просідання.
REGRESSION_PCT = 0.20
REGRESSION_ABS = {'lcp': 150, 'tbt': 100, 'total_transfer': 50 * 1024}
COMPARED_METRICS = ('lcp', 'tbt', 'total_transfer')


class PerfIngestError(ValueError):
    """Payload не пройшов валідацію -- відповідаємо 400."""


def _as_number(value, field):
    """float із payload-а. Відсікає не-числа і не-скінченні значення.

    json.loads за замовчуванням приймає нестандартні NaN/Infinity, а
    int(round(inf)) кидає OverflowError повз звичайний перехоплювач -- звідси
    окрема перевірка isfinite, інакше такий payload давав би 500 замість 400.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PerfIngestError(f'Поле {field} має бути числом')
    if not math.isfinite(number):
        raise PerfIngestError(f'Поле {field} має бути скінченним числом')
    return number


def _as_int(value, field, minimum=None):
    if value is None or value == '':
        return None
    result = int(round(_as_number(value, field)))
    if minimum is not None and result < minimum:
        raise PerfIngestError(f'Поле {field} не може бути менше {minimum}')
    return result


def _as_float(value, field, minimum=None):
    if value is None or value == '':
        return None
    result = _as_number(value, field)
    if minimum is not None and result < minimum:
        raise PerfIngestError(f'Поле {field} не може бути менше {minimum}')
    return result


def _int_or_zero(value):
    """М'яка версія для косметичних полів деталізації: непридатне значення
    стає нулем, а не помилкою -- через зіпсований запис у списку ресурсів
    не варто відкидати весь прогін."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(round(number)) if math.isfinite(number) else 0


def _as_text(value, limit):
    if value is None:
        return ''
    return str(value)[:limit]


def _parse_measured_at(raw):
    now = datetime.now(timezone.utc)
    if not raw:
        return now
    try:
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        raise PerfIngestError('measured_at має бути датою у форматі ISO 8601')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed > now + MAX_CLOCK_SKEW:
        raise PerfIngestError('measured_at не може бути в майбутньому')
    return parsed


def _clean_verdict(raw):
    verdict = str(raw or VERDICT_OK).upper()
    if verdict not in VERDICTS:
        raise PerfIngestError(f'Невідомий вердикт: {verdict}')
    return verdict


def _clean_resources(raw):
    """Нормалізувати список ресурсів до форми, яку очікує шаблон.

    Кожен елемент отримує name/transfer/dur незалежно від того, що прислали:
    без цього запис без 'name' валив сторінку деталей на рендері.
    """
    items = []
    for entry in list(raw or [])[:MAX_DETAIL_ITEMS]:
        if not isinstance(entry, dict):
            continue
        items.append({
            'name': _as_text(entry.get('name'), MAX_RESOURCE_NAME),
            'transfer': _int_or_zero(entry.get('transfer')),
            'dur': _int_or_zero(entry.get('dur')),
        })
    return items


def _clean_by_type(raw):
    """Лишити найважчі MAX_TYPE_BUCKETS типів у нормалізованій формі."""
    if not isinstance(raw, dict):
        return {}
    buckets = {}
    for name, bucket in raw.items():
        if not isinstance(bucket, dict):
            continue
        buckets[_as_text(name, 40)] = {
            'count': _int_or_zero(bucket.get('count')),
            'transfer': _int_or_zero(bucket.get('transfer')),
        }
    heaviest = sorted(buckets.items(), key=lambda kv: -kv[1]['transfer'])
    return dict(heaviest[:MAX_TYPE_BUCKETS])


def _clean_details(raw):
    """Лишаємо тільки те, що показує UI, у передбачуваній формі й з обмеженнями."""
    if not isinstance(raw, dict):
        return {}
    headers = raw.get('headers') if isinstance(raw.get('headers'), dict) else {}
    return {
        'by_type': _clean_by_type(raw.get('by_type')),
        'heaviest': _clean_resources(raw.get('heaviest')),
        'uncompressed': _clean_resources(raw.get('uncompressed')),
        'headers': {
            name: _as_text(headers.get(name), 200)
            for name in KEPT_HEADERS if headers.get(name)
        },
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

    # Усі метрики невід'ємні за визначенням: від'ємне значення означає
    # зіпсований payload, а не повільну сторінку -- краще 400, ніж сміття в
    # історії та безглузді дельти в порівнянні.
    page.ttfb = _as_int(raw.get('ttfb'), 'ttfb', minimum=0)
    page.fcp = _as_int(raw.get('fcp'), 'fcp', minimum=0)
    page.lcp = _as_int(raw.get('lcp'), 'lcp', minimum=0)
    page.tbt = _as_int(raw.get('tbt'), 'tbt', minimum=0)
    page.load_ms = _as_int(raw.get('load'), 'load', minimum=0)
    page.cls = _as_float(raw.get('cls'), 'cls', minimum=0)
    page.total_transfer = _as_int(raw.get('total_transfer'), 'total_transfer', minimum=0) or 0
    page.req_count = _as_int(raw.get('req_count'), 'req_count', minimum=0) or 0
    page.doc_transfer = _as_int(raw.get('doc_transfer'), 'doc_transfer', minimum=0) or 0
    page.doc_decoded = _as_int(raw.get('doc_decoded'), 'doc_decoded', minimum=0) or 0
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
        runs_per_page=_as_int(payload.get('runs_per_page'), 'runs_per_page', minimum=0) or 0,
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

    # Прогін уже збережено, тож збій прибирання не має перетворюватись на 500:
    # інакше клієнт вважав би надсилання невдалим і повторив --push, створивши дубль.
    try:
        _prune_old_runs()
    except Exception:
        db.session.rollback()
        logger.exception('perf: не вдалося прибрати застарілі прогони')

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
