#!/usr/bin/env python
"""Вимірювач швидкості завантаження сторінок (Playwright + Chrome DevTools Protocol).

Для кожної сторінки збирає:
  * Navigation Timing -- TTFB, DOMContentLoaded, load;
  * Core Web Vitals -- FCP, LCP, CLS, TBT (сума long-task понад 50 мс);
  * вагу передачі -- кількість запитів і transferSize у розрізі типів ресурсів;
  * найважчі та нестиснені ресурси.

Кожна сторінка міряється N разів (типово 3) у свіжому контексті з порожнім
кешем -- у звіт іде МЕДІАНА, щоб одиничний мережевий сплеск не спотворив
картину. Метрики звіряються з бюджетами (див. BUDGETS) і кожна сторінка
отримує вердикт OK / WARN / FAIL.

Профілі:
  desktop -- 1440x900, без тротлінгу (верхня межа можливого);
  mobile  -- 390x844, CPU x4 + мережа Slow 4G (наближено до реального смартфона).

Використання:
    python tools/perf/perf_check.py
    python tools/perf/perf_check.py --base-url http://127.0.0.1:5001 --profile desktop
    python tools/perf/perf_check.py --path / --path /courses/ --runs 5
    python tools/perf/perf_check.py --json runs/today.json
    python tools/perf/perf_check.py --baseline runs/before.json   # порівняти з попереднім
    python tools/perf/perf_check.py --push https://plasma-regen.com/api/v1/perf/runs \
        --token <ключ з /admin/perf> --note "після лінивої recaptcha"

Код повернення: 0 -- усі сторінки в бюджеті; 1 -- є FAIL; 2 -- сторінки не
виміряні (мережа/таймаут); 3 -- виміряно, але надсилання в адмінку впало.
Придатний як гейт у CI.

ВАЖЛИВО: інструмент робить лише GET-запити на публічні сторінки -- дані не
змінює, форм не надсилає.

Залежності: playwright (`pip install playwright && playwright install chromium`).
Повний опис і трактування метрик -- tools/perf/README.md
"""
import argparse
import json
import os
import socket
import statistics
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

DEFAULT_BASE_URL = 'https://plasma-regen.com'

# Версія формату payload-а для /api/v1/perf/runs. Піднімати при зміні полів.
TOOL_VERSION = '1.0'

# Ключові публічні сторінки: головна, каталоги, типова картка курсу/тренера,
# блог і форми входу/реєстрації -- найгарячіші шляхи трафіку.
DEFAULT_PATHS = [
    '/',
    '/courses/',
    '/courses/bazovyi-kurs-z-postanovkoyu-ruky',
    '/trainers/',
    '/trainers/gusak-valeriia',
    '/blog/',
    '/contact',
    '/auth/login',
    '/auth/register',
]

PROFILES = {
    'desktop': dict(
        viewport={'width': 1440, 'height': 900}, is_mobile=False, dsf=1,
        cpu_rate=1, net=None,
    ),
    'mobile': dict(
        viewport={'width': 390, 'height': 844}, is_mobile=True, dsf=2,
        cpu_rate=4,
        # Slow 4G за пресетом DevTools: 1.6 Мбіт/с вниз, 750 Кбіт/с вгору, RTT 150 мс.
        net=dict(latency=150, downloadThroughput=1_600_000 / 8, uploadThroughput=750_000 / 8),
    ),
}

# Бюджети: (межа WARN, межа FAIL). Для mobile -- офіційні пороги Core Web
# Vitals; для desktop -- жорсткіші, бо тротлінгу немає і будь-яке уповільнення
# там означає проблему на сервері або в критичному шляху рендеру.
BUDGETS = {
    'mobile': {
        'ttfb': (800, 1800),
        'lcp': (2500, 4000),
        'tbt': (200, 600),
        'cls': (0.1, 0.25),
        'total_transfer': (1_200 * 1024, 2_500 * 1024),
    },
    'desktop': {
        'ttfb': (400, 800),
        'lcp': (1200, 2500),
        'tbt': (150, 350),
        'cls': (0.1, 0.25),
        'total_transfer': (1_200 * 1024, 2_500 * 1024),
    },
}

BUDGET_LABELS = {
    'ttfb': 'TTFB', 'lcp': 'LCP', 'tbt': 'TBT', 'cls': 'CLS',
    'total_transfer': 'вага сторінки',
}

# Регресія відносно базової лінії: гірше і на відсоток, і на абсолют
# (щоб дрібні коливання мережі не вважались регресією).
REGRESSION_PCT = 0.20
REGRESSION_ABS = {'lcp': 150, 'tbt': 100, 'total_transfer': 50 * 1024}

# Скрипт-збирач вебвіталів. Ставиться ДО навігації, тому ловить і ранній LCP.
COLLECTOR = """
window.__perf = {lcp: 0, cls: 0, tbt: 0, longTasks: 0};
try {
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) window.__perf.lcp = e.startTime;
  }).observe({type: 'largest-contentful-paint', buffered: true});
} catch (e) {}
try {
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) if (!e.hadRecentInput) window.__perf.cls += e.value;
  }).observe({type: 'layout-shift', buffered: true});
} catch (e) {}
try {
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) {
      window.__perf.longTasks += 1;
      window.__perf.tbt += Math.max(0, e.duration - 50);
    }
  }).observe({type: 'longtask', buffered: true});
} catch (e) {}
"""

# Дістає підсумки після завантаження. transferSize == 0 для cross-origin без
# Timing-Allow-Origin -- такі ресурси видно у переліку, але вага в них нульова.
EXTRACTOR = """
() => {
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const fcpEntry = performance.getEntriesByName('first-contentful-paint')[0];
  const res = performance.getEntriesByType('resource').map(r => ({
    name: r.name,
    type: r.initiatorType,
    transfer: r.transferSize || 0,
    decoded: r.decodedBodySize || 0,
    dur: Math.round(r.duration),
  }));
  return {
    ttfb: Math.round((nav.responseStart || 0) - (nav.requestStart || 0)),
    domContentLoaded: Math.round(nav.domContentLoadedEventEnd || 0),
    load: Math.round(nav.loadEventEnd || 0),
    docTransfer: nav.transferSize || 0,
    docDecoded: nav.decodedBodySize || 0,
    fcp: fcpEntry ? Math.round(fcpEntry.startTime) : 0,
    lcp: Math.round(window.__perf.lcp),
    cls: Math.round(window.__perf.cls * 1000) / 1000,
    tbt: Math.round(window.__perf.tbt),
    longTasks: window.__perf.longTasks,
    resources: res,
  };
}
"""


def fmt_kb(n):
    return f'{n / 1024:.0f} KB' if n else '-'


def verdict_for(profile, metric, value):
    """OK / WARN / FAIL за бюджетом. Невідома метрика або None -> OK."""
    limits = BUDGETS.get(profile, {}).get(metric)
    if limits is None or value is None:
        return 'OK'
    warn, fail = limits
    if value > fail:
        return 'FAIL'
    if value > warn:
        return 'WARN'
    return 'OK'


def worst_verdict(verdicts):
    for level in ('FAIL', 'WARN'):
        if level in verdicts:
            return level
    return 'OK'


def measure_once(browser, url, profile, doc_headers_sink):
    """Один прогін у свіжому контексті (порожній кеш). Повертає dict метрик."""
    cfg = PROFILES[profile]
    ctx = browser.new_context(
        viewport=cfg['viewport'],
        is_mobile=cfg['is_mobile'],
        device_scale_factor=cfg['dsf'],
    )
    page = ctx.new_page()
    page.add_init_script(COLLECTOR)

    cdp = ctx.new_cdp_session(page)
    if cfg['cpu_rate'] > 1:
        cdp.send('Emulation.setCPUThrottlingRate', {'rate': cfg['cpu_rate']})
    if cfg['net']:
        cdp.send('Network.emulateNetworkConditions', {
            'offline': False,
            'latency': cfg['net']['latency'],
            'downloadThroughput': cfg['net']['downloadThroughput'],
            'uploadThroughput': cfg['net']['uploadThroughput'],
        })

    status = None
    try:
        resp = page.goto(url, wait_until='load', timeout=60000)
        if resp:
            status = resp.status
            # Заголовки документа однакові між прогонами -- беремо з першого.
            if doc_headers_sink is not None and not doc_headers_sink:
                h = resp.headers
                doc_headers_sink.update({
                    'content-encoding': h.get('content-encoding', '(немає)'),
                    'cache-control': h.get('cache-control', '(немає)'),
                    'server': h.get('server', ''),
                })
        # Даємо шанс відкладеним LCP-кандидатам і long-task-ам після load.
        page.wait_for_timeout(1200)
        data = page.evaluate(EXTRACTOR)
    except Exception as exc:
        return {'error': str(exc)[:120], 'status': status}
    finally:
        try:
            cdp.detach()
        except Exception:
            pass
        page.close()
        ctx.close()

    data['status'] = status
    return data


def summarize_resources(resources, doc_transfer):
    """Агрегація ресурсів за типом + топ найважчих і нестиснених."""
    by_type = {}
    for r in resources:
        t = r['type'] or 'other'
        b = by_type.setdefault(t, {'count': 0, 'transfer': 0})
        b['count'] += 1
        b['transfer'] += r['transfer']
    total = sum(b['transfer'] for b in by_type.values()) + doc_transfer
    heaviest = sorted(resources, key=lambda r: -r['transfer'])[:5]
    # Текстовий ресурс вважаємо нестисненим, якщо трансфер близький до
    # розпакованого розміру (gzip/br дав би відчутно менше).
    uncompressed = [
        r for r in resources
        if r['decoded'] > 20_000 and r['transfer'] >= r['decoded'] * 0.92
        and any(r['name'].split('?')[0].endswith(e) for e in ('.css', '.js', '.svg', '.json'))
    ]
    return {
        'total_transfer': total,
        'req_count': len(resources) + 1,
        'by_type': by_type,
        'heaviest': heaviest,
        'uncompressed': uncompressed[:5],
    }


def median_of(runs, key):
    vals = [r[key] for r in runs if isinstance(r.get(key), (int, float))]
    return round(statistics.median(vals), 3) if vals else None


def measure_page(browser, url, profile, runs_count):
    """Кілька прогонів -> медіанні метрики + ресурсний зріз медіанного прогону."""
    runs, headers = [], {}
    for _ in range(runs_count):
        runs.append(measure_once(browser, url, profile, headers))
    ok = [r for r in runs if 'error' not in r]
    if not ok:
        return {'url': url, 'error': runs[0].get('error', 'unknown')}

    med_lcp = median_of(ok, 'lcp')
    # Ресурсний зріз беремо з прогону, найближчого до медіанного LCP.
    pick = min(ok, key=lambda r: abs(r['lcp'] - med_lcp))
    res = summarize_resources(pick['resources'], pick['docTransfer'])
    row = {
        'url': url,
        'status': pick['status'],
        'ttfb': median_of(ok, 'ttfb'),
        'fcp': median_of(ok, 'fcp'),
        'lcp': med_lcp,
        'tbt': median_of(ok, 'tbt'),
        'cls': median_of(ok, 'cls'),
        'dcl': median_of(ok, 'domContentLoaded'),
        'load': median_of(ok, 'load'),
        'doc_transfer': pick['docTransfer'],
        'doc_decoded': pick['docDecoded'],
        'headers': headers,
        'runs_ok': len(ok),
        **res,
    }
    row['budget'] = {m: verdict_for(profile, m, row.get(m)) for m in BUDGETS[profile]}
    row['verdict'] = worst_verdict(set(row['budget'].values()))
    return row


def print_details(profile, rows):
    """Деталізація по найповільнішій сторінці профілю -- куди дивитись далі."""
    if not rows:
        return
    worst = max(rows, key=lambda r: r['lcp'] or 0)
    print(f'\n  Найповільніша ({profile}): {worst["url"]}  LCP={worst["lcp"]}мс')
    print(f'  Документ: {fmt_kb(worst["doc_transfer"])} по мережі '
          f'/ {fmt_kb(worst["doc_decoded"])} розпаковано, '
          f'стиснення: {worst["headers"].get("content-encoding")}, '
          f'cache-control: {worst["headers"].get("cache-control")}')
    print('  Вага за типами: ' + ', '.join(
        f'{t}x{b["count"]} {fmt_kb(b["transfer"])}'
        for t, b in sorted(worst['by_type'].items(), key=lambda kv: -kv[1]['transfer'])))
    print('  Найважчі ресурси:')
    for r in worst['heaviest']:
        print(f'    {fmt_kb(r["transfer"]):>9}  {r["dur"]:>5}мс  '
              f'{r["name"].split("/")[-1][:58]}')
    if worst['uncompressed']:
        print('  Без стиснення (текстові >20 KB):')
        for r in worst['uncompressed']:
            print(f'    {fmt_kb(r["transfer"]):>9}  {r["name"].split("/")[-1][:58]}')


def print_violations(report):
    """Перелік метрик, що вийшли за бюджет, з фактичним значенням і межею."""
    lines = []
    for key, row in report.items():
        if 'error' in row:
            continue
        profile = key.split(':', 1)[0]
        for metric, verdict in row['budget'].items():
            if verdict == 'OK':
                continue
            warn, fail = BUDGETS[profile][metric]
            value = row.get(metric)
            shown = fmt_kb(value) if metric == 'total_transfer' else value
            limit = fmt_kb(warn) if metric == 'total_transfer' else warn
            lines.append(f'  [{verdict:<4}] {key:<48} {BUDGET_LABELS[metric]}: '
                         f'{shown} (бюджет {limit})')
    if lines:
        print(f'\n{"=" * 78}\n  ПОРУШЕННЯ БЮДЖЕТУ\n{"=" * 78}')
        print('\n'.join(sorted(lines)))
    else:
        print('\nУсі сторінки в межах бюджету.')


def print_baseline_diff(report, baseline_path):
    """Порівняння з попереднім прогоном: що прискорилось, що просіло."""
    try:
        with open(baseline_path, encoding='utf-8') as f:
            base = json.load(f)
    except Exception as exc:
        print(f'\nБазову лінію не прочитано ({baseline_path}): {exc}')
        return

    print(f'\n{"=" * 78}\n  ПОРІВНЯННЯ З БАЗОВОЮ ЛІНІЄЮ: {baseline_path}\n{"=" * 78}')
    print(f'{"сторінка":<50}{"LCP":>14}{"TBT":>14}{"вага":>16}')
    print('-' * 94)
    regressions = []
    for key, row in report.items():
        if 'error' in row or key not in base or 'error' in base[key]:
            continue
        cells = []
        for metric in ('lcp', 'tbt', 'total_transfer'):
            now, was = row.get(metric), base[key].get(metric)
            if now is None or was is None:
                cells.append('-')
                continue
            delta = now - was
            unit = fmt_kb(abs(delta)) if metric == 'total_transfer' else f'{abs(delta):.0f}мс'
            sign = '+' if delta > 0 else ('-' if delta < 0 else '=')
            cells.append(f'{sign}{unit}' if delta else '=')
            if (delta > REGRESSION_ABS[metric]
                    and was > 0 and delta / was > REGRESSION_PCT):
                regressions.append(f'  {key}: {BUDGET_LABELS[metric]} '
                                   f'{was} -> {now} ({sign}{unit})')
        print(f'{key[:48]:<50}{cells[0]:>14}{cells[1]:>14}{cells[2]:>16}')
    if regressions:
        print(f'\n  Регресії (гірше на >{int(REGRESSION_PCT * 100)}%):')
        print('\n'.join(regressions))
    else:
        print('\n  Регресій відносно базової лінії немає.')


def build_payload(report, base_url, runs_count, note, source):
    """Зібрати тіло запиту для POST /api/v1/perf/runs.

    Межі бюджетів їдуть разом із прогоном: єдиним джерелом істини лишається
    цей інструмент, а адмінка показує рівно ті межі, за якими рахувався
    вердикт цього заміру (інакше зміна порогів переписала б історію).
    """
    pages = []
    for key, row in report.items():
        profile, path = key.split(':', 1)
        if 'error' in row:
            pages.append({
                'profile': profile, 'path': path,
                'url': row.get('url', ''), 'error': row['error'][:255],
            })
            continue
        pages.append({
            'profile': profile,
            'path': path,
            'url': row['url'],
            'status': row['status'],
            'ttfb': row['ttfb'],
            'fcp': row['fcp'],
            'lcp': row['lcp'],
            'tbt': row['tbt'],
            'cls': row['cls'],
            'load': row['load'],
            'total_transfer': row['total_transfer'],
            'req_count': row['req_count'],
            'doc_transfer': row['doc_transfer'],
            'doc_decoded': row['doc_decoded'],
            'verdict': row['verdict'],
            'budget': row['budget'],
            'details': {
                'by_type': row['by_type'],
                'heaviest': row['heaviest'],
                'uncompressed': row['uncompressed'],
                'headers': row['headers'],
            },
        })
    return {
        'measured_at': datetime.now(timezone.utc).isoformat(),
        'base_url': base_url,
        'source': source or socket.gethostname(),
        'note': note,
        'runs_per_page': runs_count,
        'tool_version': TOOL_VERSION,
        'budgets': BUDGETS,
        'pages': pages,
    }


def load_report(path):
    """Прочитати збережений --json прогін для повторного надсилання."""
    try:
        with open(path, encoding='utf-8') as f:
            report = json.load(f)
    except (OSError, ValueError) as exc:
        raise SystemExit(f'Не вдалося прочитати {path}: {exc}')
    if not isinstance(report, dict) or not report:
        raise SystemExit(f'{path} не схожий на збережений прогін')
    return report


def base_url_from_report(report, fallback):
    """Дістати корінь сайту з URL-ів прогону -- надійніше за --base-url,
    який під час повторного надсилання може відрізнятись від зміряного."""
    for row in report.values():
        url = row.get('url')
        if url:
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                return f'{parsed.scheme}://{parsed.netloc}'
    return fallback


def push_report(url, token, payload):
    """Надіслати прогін в адмінку. True -- прийнято."""
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        url, data=data, method='POST',
        headers={'Content-Type': 'application/json', 'X-API-Key': token},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'ignore')[:200]
        print(f'\nНадсилання відхилено: HTTP {exc.code} {detail}')
        if exc.code == 404:
            print('  404 означає, що приймання вимкнено -- згенеруйте ключ на /admin/perf.')
        return False
    except Exception as exc:
        print(f'\nНадсилання не вдалося: {exc}')
        return False

    print(f'\nНадіслано в адмінку: прогін #{body.get("id")} ({body.get("verdict")}) '
          f'-> {body.get("admin_url")}')
    return True


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base-url', default=DEFAULT_BASE_URL)
    ap.add_argument('--path', action='append', default=[],
                    help='шлях для заміру (можна кілька); без цього -- типовий набір')
    ap.add_argument('--profile', action='append', default=[],
                    choices=list(PROFILES), help='desktop / mobile (типово обидва)')
    ap.add_argument('--runs', type=int, default=3, help='прогонів на сторінку (медіана)')
    ap.add_argument('--json', default='', help='зберегти сирі дані у файл')
    ap.add_argument('--baseline', default='',
                    help='JSON попереднього прогону для порівняння')
    ap.add_argument('--push', default=os.environ.get('PERF_PUSH_URL', ''),
                    help='URL приймання в адмінці (або змінна PERF_PUSH_URL)')
    ap.add_argument('--token', default=os.environ.get('PERF_PUSH_TOKEN', ''),
                    help='ключ приймання з /admin/perf (або змінна PERF_PUSH_TOKEN)')
    ap.add_argument('--push-json', default='',
                    help='надіслати вже збережений --json прогін без повторного заміру')
    ap.add_argument('--note', default='', help='мітка прогону для адмінки')
    ap.add_argument('--source', default='',
                    help='мітка машини (типово -- ім\'я хоста)')
    args = ap.parse_args()

    if args.push and not args.token:
        ap.error('--push потребує --token (або змінної PERF_PUSH_TOKEN)')
    if args.push_json and not args.push:
        ap.error('--push-json потребує --push з адресою приймання')

    base = args.base_url.rstrip('/')
    paths = args.path or DEFAULT_PATHS
    profiles = args.profile or list(PROFILES)
    report = {}

    # Доставка відокремлена від заміру: прогін міг бути зроблений раніше (або
    # на іншій машині), і повторювати кількахвилинний замір лише заради
    # надсилання немає сенсу.
    if args.push_json:
        report = load_report(args.push_json)
        measured = [v for v in report.values() if 'error' not in v]
        # Скільки прогонів було насправді -- беремо з самого файлу, а не з
        # --runs: прапорець при повторному надсиланні може не збігатися.
        runs_done = max((v.get('runs_ok') or 0 for v in measured), default=0) or args.runs
        payload = build_payload(
            report, base_url_from_report(report, base),
            runs_done, args.note, args.source,
        )
        print(f'Надсилаю збережений прогін: {args.push_json} '
              f'({len(measured)} виміряних сторінок)')
        if not push_report(args.push, args.token, payload):
            return 3
        return 1 if any(v['verdict'] == 'FAIL' for v in measured) else 0

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for profile in profiles:
                print(f'\n{"=" * 92}\n  {profile.upper()}  --  {base}'
                      f'  ({args.runs} прогони/сторінка, медіана)\n{"=" * 92}')
                print(f'{"сторінка":<42}{"TTFB":>7}{"FCP":>7}{"LCP":>7}{"TBT":>7}'
                      f'{"CLS":>7}{"load":>7}{"вага":>9}{"req":>5}{"":>7}')
                print('-' * 99)
                for path in paths:
                    url = urljoin(base + '/', path.lstrip('/'))
                    row = measure_page(browser, url, profile, args.runs)
                    report[f'{profile}:{path}'] = row
                    label = urlparse(url).path[:40]
                    if 'error' in row:
                        print(f'{label:<42}  ПОМИЛКА: {row["error"][:44]}')
                        continue
                    print(f'{label:<42}{row["ttfb"]:>6}м{row["fcp"]:>6}м{row["lcp"]:>6}м'
                          f'{row["tbt"]:>6}м{row["cls"]:>7}{row["load"]:>6}м'
                          f'{fmt_kb(row["total_transfer"]):>9}{row["req_count"]:>5}'
                          f'{row["verdict"]:>7}')
                print_details(profile, [v for k, v in report.items()
                                        if k.startswith(profile + ':') and 'error' not in v])
        finally:
            browser.close()

    print_violations(report)
    if args.baseline:
        print_baseline_diff(report, args.baseline)

    if args.json:
        folder = os.path.dirname(os.path.abspath(args.json))
        os.makedirs(folder, exist_ok=True)
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f'\nСирі дані -> {args.json}')

    measured = [v for v in report.values() if 'error' not in v]
    if not measured:
        print('\nЖодної сторінки не виміряно -- перевір --base-url і доступність сайту.')
        return 2

    if args.push:
        payload = build_payload(report, base, args.runs, args.note, args.source)
        if not push_report(args.push, args.token, payload):
            # Заміри валідні, але в адмінку не потрапили -- окремий код, щоб
            # у CI не сплутати збій доставки з порушенням бюджету.
            return 3

    if any(v['verdict'] == 'FAIL' for v in measured):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
