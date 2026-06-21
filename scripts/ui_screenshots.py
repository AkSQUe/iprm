#!/usr/bin/env python
"""UI-скриншотер: обхід сайту + повносторінкові скріни у 3 viewport-ах.

Краулер стартує з BASE_URL, переходить за внутрішніми посиланнями (BFS,
лише same-origin, лише HTML) і зберігає повносторінкові скріншоти у трьох
варіантах адаптивності -- desktop / tablet / mobile. Структура тек дзеркалить
шлях URL, тож по дереву зручно проходитись очима у пошуку UI-проблем.

Приклад дерева виводу:
    ui-shots/
      index.html                 <- галерея з мініатюрами (відкрий у браузері)
      home/{desktop,tablet,mobile}.png
      courses/{desktop,tablet,mobile}.png
      courses/bls/{desktop,tablet,mobile}.png
      admin/registrations/{...}.png

Використання:
    # публічні сторінки локального інстансу
    python scripts/ui_screenshots.py --base-url http://127.0.0.1:5001

    # разом з адмінкою (логін перед обходом)
    python scripts/ui_screenshots.py --base-url http://127.0.0.1:5001 \
        --login-email admin@example.com --login-password secret \
        --start-path /admin/registrations

    # лише певний розділ
    python scripts/ui_screenshots.py --base-url http://127.0.0.1:5001 \
        --only-prefix /admin --start-path /admin

ВАЖЛИВО (про БД): краулер робить лише GET-запити, але щоб не зачіпати
продакшн-дані, запускай його проти ЛОКАЛЬНОГО інстансу (бажано з ізольованою
БД). Роути logout/invoice/завантажень свідомо пропускаються.

Залежності: playwright (`pip install playwright && playwright install chromium`).
"""
import argparse
import re
import sys
from collections import deque
from urllib.parse import urldefrag, urljoin, urlparse

from playwright.sync_api import sync_playwright

# (width, height, is_mobile, device_scale_factor)
VIEWPORTS = {
    'desktop': dict(width=1440, height=900, is_mobile=False, device_scale_factor=1),
    'tablet':  dict(width=820,  height=1180, is_mobile=True,  device_scale_factor=2),
    'mobile':  dict(width=390,  height=844,  is_mobile=True,  device_scale_factor=2),
}

# Не ходимо за посиланнями на файли/ресурси та небезпечні/нудні роути.
SKIP_EXT = (
    '.pdf', '.xlsx', '.xls', '.zip', '.doc', '.docx', '.csv',
    '.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.ico',
    '.css', '.js', '.xml', '.json', '.txt', '.heic', '.psd', '.mp4', '.webm',
)
SKIP_SUBSTR = (
    '/logout', '/invoice', '/download', '/export',
    '/delete', '/revoke', '/remove',
    '/static/', '/media/', '/ngx-i/', '/api/',
)


def norm_url(base_netloc, current_url, href):
    """Абсолютизувати href, відкинути фрагмент, лишити тільки same-origin HTTP(S)."""
    if not href:
        return None
    href = href.strip()
    if href.startswith(('mailto:', 'tel:', 'javascript:', 'data:', '#')):
        return None
    absolute = urljoin(current_url, href)
    absolute, _frag = urldefrag(absolute)
    parsed = urlparse(absolute)
    if parsed.scheme not in ('http', 'https'):
        return None
    if parsed.netloc != base_netloc:
        return None
    low = absolute.lower()
    if low.endswith(SKIP_EXT):
        return None
    if any(s in low for s in SKIP_SUBSTR):
        return None
    return absolute


def key_for(url, include_query):
    """Ключ дедуплікації: шлях (+query за бажанням). Без trailing slash."""
    p = urlparse(url)
    path = p.path.rstrip('/') or '/'
    if include_query and p.query:
        return f'{path}?{p.query}'
    return path


def dir_for(url):
    """URL -> відносна тека виводу, що дзеркалить шлях."""
    p = urlparse(url)
    path = p.path.strip('/')
    if not path:
        base = 'home'
    else:
        segs = [re.sub(r'[^A-Za-z0-9._-]+', '_', s) for s in path.split('/') if s]
        base = '/'.join(segs) or 'home'
    if p.query:
        base = base + '/_q_' + re.sub(r'[^A-Za-z0-9._-]+', '_', p.query)[:60]
    return base


def safe_goto(page, url, timeout=25000):
    """Перейти на URL стійко до 301-редіректів і клієнтських навігацій.

    'interrupted by another navigation' / ERR_ABORTED трапляється, коли сервер
    редіректить (напр. trailing-slash) саме на commit. Ескалюємо wait_until і
    робимо повторну спробу, перш ніж здатися.
    """
    last = None
    for wait_until in ('load', 'domcontentloaded', 'commit'):
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout)
            return True
        except Exception as exc:
            last = str(exc)
            msg = last.lower()
            if 'interrupted' in msg or 'aborted' in msg or 'timeout' in msg:
                try:
                    page.wait_for_timeout(400)
                except Exception:
                    pass
                continue
            break
    if last:
        print(f'        (goto fail) {url}: {last[:90]}')
    return False


def trigger_lazy_load(page):
    """Прокрутити сторінку донизу й назад угору, щоб тригернути lazy-load
    (зображення/секції). Без цього full_page-скрін має порожні блоки нижче згину."""
    try:
        page.evaluate(
            """() => new Promise(resolve => {
                let total = 0; const step = Math.max(400, window.innerHeight - 100);
                const timer = setInterval(() => {
                    window.scrollBy(0, step); total += step;
                    if (total >= document.body.scrollHeight) {
                        clearInterval(timer); window.scrollTo(0, 0); resolve();
                    }
                }, 120);
            })"""
        )
        page.wait_for_timeout(500)
    except Exception:
        pass


def dismiss_cookie(page):
    """Прибрати cookie-банер (перекриває контент). Одного разу на контекст."""
    for name in ('Прийняти', 'Лише необхідні', 'Accept', 'Погоджуюсь'):
        try:
            btn = page.get_by_role('button', name=name)
            if btn.count():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(300)
                return
        except Exception:
            pass


def login(page, base_url, email, password, login_path):
    url = urljoin(base_url, login_path)
    page.goto(url, wait_until='domcontentloaded')
    dismiss_cookie(page)
    try:
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', password)
        page.get_by_role('button', name=re.compile('Увійти|Login|Sign in', re.I)).first.click()
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(500)
        ok = '/login' not in page.url
        print(f'[login] {"OK" if ok else "FAILED"} -> {page.url}')
        return ok
    except Exception as exc:
        print(f'[login] error: {exc}')
        return False


def crawl(context, base_url, start_urls, max_pages, include_query, only_prefix):
    """BFS-обхід. Повертає впорядкований список унікальних URL."""
    base_netloc = urlparse(base_url).netloc
    page = context.new_page()
    dismiss_cookie_done = False

    seen = {}          # key -> url (перший знайдений)
    queue = deque()
    for u in start_urls:
        k = key_for(u, include_query)
        if k not in seen:
            seen[k] = u
            queue.append(u)

    ordered = []
    while queue and len(ordered) < max_pages:
        url = queue.popleft()
        if not safe_goto(page, url, timeout=20000):
            print(f'[crawl] skip (load error) {url}')
            continue
        if not dismiss_cookie_done:
            dismiss_cookie(page)
            dismiss_cookie_done = True
        ordered.append(url)
        print(f'[crawl] {len(ordered):>3}. {url}')

        try:
            hrefs = page.eval_on_selector_all(
                'a[href]', 'els => els.map(e => e.getAttribute("href"))'
            )
        except Exception:
            hrefs = []
        for href in hrefs:
            nu = norm_url(base_netloc, url, href)
            if not nu:
                continue
            if only_prefix and not urlparse(nu).path.startswith(only_prefix):
                continue
            k = key_for(nu, include_query)
            if k in seen:
                continue
            seen[k] = nu
            queue.append(nu)

    page.close()
    return ordered


def shoot(browser, urls, out_dir, base_url, login_args):
    """Для кожного viewport: новий контекст, логін (за потреби), скріни всіх URL."""
    import os
    results = []  # (rel_dir, url)
    for vp_name, vp in VIEWPORTS.items():
        ctx = browser.new_context(
            viewport={'width': vp['width'], 'height': vp['height']},
            is_mobile=vp['is_mobile'],
            device_scale_factor=vp['device_scale_factor'],
        )
        page = ctx.new_page()
        if login_args:
            login(page, base_url, *login_args)
        dismissed = False
        for url in urls:
            rel = dir_for(url)
            folder = os.path.join(out_dir, rel)
            os.makedirs(folder, exist_ok=True)
            if not safe_goto(page, url, timeout=25000):
                print(f'[shot:{vp_name}] FAIL {url}')
                continue
            if not dismissed:
                dismiss_cookie(page)
                dismissed = True
            page.wait_for_timeout(400)
            trigger_lazy_load(page)
            try:
                page.screenshot(path=os.path.join(folder, f'{vp_name}.png'), full_page=True)
            except Exception as exc:
                print(f'[shot:{vp_name}] screenshot error {url}: {str(exc)[:80]}')
                continue
            if vp_name == 'desktop':
                results.append((rel, url))
        page.close()
        ctx.close()
        print(f'[shot] {vp_name}: done ({len(urls)} pages)')
    return results


def write_index(out_dir, results):
    """Згенерувати index.html-галерею з мініатюрами 3 viewport-ів на сторінку."""
    import html
    import os
    rows = []
    for rel, url in sorted(results):
        cells = ''.join(
            f'<figure><figcaption>{vp}</figcaption>'
            f'<a href="{rel}/{vp}.png" target="_blank">'
            f'<img loading="lazy" src="{rel}/{vp}.png"></a></figure>'
            for vp in VIEWPORTS
        )
        rows.append(
            f'<section><h2>{html.escape(url)}</h2>'
            f'<div class="row">{cells}</div></section>'
        )
    doc = (
        '<!doctype html><meta charset="utf-8">'
        '<title>UI screenshots</title>'
        '<style>'
        'body{font:14px/1.4 system-ui,sans-serif;margin:24px;background:#f5f5f7;color:#111}'
        'h1{font-size:20px}h2{font-size:14px;color:#444;word-break:break-all;margin:0 0 8px}'
        'section{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin:0 0 20px}'
        '.row{display:flex;gap:16px;flex-wrap:wrap}'
        'figure{margin:0;flex:1 1 280px;min-width:220px}'
        'figcaption{font-size:12px;color:#888;margin-bottom:4px;text-transform:uppercase;letter-spacing:.04em}'
        'img{width:100%;border:1px solid #ddd;border-radius:8px;background:#fff;'
        'max-height:520px;object-fit:contain;object-position:top}'
        '</style>'
        f'<h1>UI screenshots — {len(results)} сторінок × {len(VIEWPORTS)} viewport-и</h1>'
        + ''.join(rows)
    )
    with open(os.path.join(out_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(doc)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base-url', default='http://127.0.0.1:5001')
    ap.add_argument('--out', default='ui-shots', help='тека виводу (default: ui-shots)')
    ap.add_argument('--max-pages', type=int, default=200)
    ap.add_argument('--start-path', action='append', default=[],
                    help='додаткові стартові шляхи (можна кілька), напр. /admin')
    ap.add_argument('--only-prefix', default='', help='обходити лише шляхи з цим префіксом')
    ap.add_argument('--include-query', action='store_true',
                    help='вважати URL з різними query різними сторінками')
    ap.add_argument('--login-email', default='')
    ap.add_argument('--login-password', default='')
    ap.add_argument('--login-path', default='/auth/login')
    args = ap.parse_args()

    base_url = args.base_url.rstrip('/')
    start_urls = [base_url + '/'] + [urljoin(base_url + '/', p.lstrip('/')) for p in args.start_path]
    login_args = None
    if args.login_email and args.login_password:
        login_args = (args.login_email, args.login_password, args.login_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # Фаза 1: обхід (у логіненому контексті, щоб бачити admin-посилання).
        crawl_ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        cpage = crawl_ctx.new_page()
        if login_args:
            login(cpage, base_url, *login_args)
        cpage.close()
        urls = crawl(crawl_ctx, base_url, start_urls, args.max_pages,
                     args.include_query, args.only_prefix)
        crawl_ctx.close()

        if not urls:
            print('Не знайдено жодної сторінки. Перевір --base-url / доступність сайту.')
            sys.exit(1)

        # Фаза 2: скріншоти у 3 viewport-ах.
        results = shoot(browser, urls, args.out, base_url, login_args)
        browser.close()

    write_index(args.out, results)
    print(f'\nГотово: {len(results)} сторінок -> {args.out}/  (відкрий {args.out}/index.html)')


if __name__ == '__main__':
    main()
