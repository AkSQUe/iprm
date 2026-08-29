"""Спільні хелпери SEO-сторожів: перелік публічних сторінок і список
відомого боргу."""
import json
import re

# Розділи, закриті від індексації (мають X-Robots-Tag у своїх __init__.py).
PRIVATE_BLUEPRINTS = {'admin', 'auth', 'payments', 'quiz', 'registration'}

# Службові ендпоінти: віддають не HTML, тож HTML-твердження до них не
# застосовні. main.offer_pdf -- PDF (application/pdf), blog.feed -- RSS
# (application/rss+xml), courses.calendar_json -- JSON: жодне з них не
# віддає HTML-сторінку.
SERVICE_ENDPOINTS = {
    'static', 'main.robots', 'main.sitemap', 'media.serve',
    'main.offer_pdf', 'blog.feed', 'courses.calendar_json',
}

# Відомий SEO-борг: ендпоінт -> причина. Порожньо -- борг закритий.
# Додавати запис можна лише разом із задачею, що його прибирає.
KNOWN_SEO_DEBT = {}

# Цільові межі довжин зі специфікації.
TITLE_MIN, TITLE_MAX = 30, 60
DESC_MIN, DESC_MAX = 120, 160

# Сторінки, чию довжину не виправити без рішення про контент: ендпоінт ->
# причина. Межі НЕ пом'якшуються -- виняток завжди іменований. Задача 1
# занесла сюди 13 записів; Задача 4 переписала title/description 12 із
# них у межі 30-60/120-160, зберігши сенс. Один запис (blog.index)
# довелось повернути в раунді фіксів: перша спроба розширення опису
# називала конкретні теми (PRP-терапія, дослідження біологічного віку),
# яких блог на момент написання не покривав -- у деві таблиця постів
# порожня, тож жодну тематичну заяву перевірити неможливо, а вигадувати
# теми для чужого редакційного розділу -- вже не SEO-копірайтинг.
LENGTH_EXCEPTIONS = {
    'blog.index': (
        'description 87 симв. -- блог наповнюється редакційно і на момент '
        'написання порожній: жодної конкретної теми (курси, дослідження, '
        'терапії) додати в опис чесно не можна -- це були б непідтверджені '
        'заяви про вміст, якого ще немає. Розширити без конкретики означало '
        'б штучно заповнити текст словами заради довжини, а не описати '
        'сторінку -- тому лишається винятком, а не переписом.'
    ),
}


def public_endpoints(app):
    """Ендпоінти публічних HTML-сторінок без обовʼязкових параметрів.

    Динамічні сторінки (курс, тренер, стаття) сюди не потрапляють -- вони
    потребують рядків у БД і перевіряються окремими тестами з фікстурами.
    """
    endpoints = set()
    for rule in app.url_map.iter_rules():
        if 'GET' not in rule.methods:
            continue
        if rule.endpoint in SERVICE_ENDPOINTS:
            continue
        if rule.endpoint.split('.')[0] in PRIVATE_BLUEPRINTS:
            continue
        # lang_code має дефолт, решта параметрів робить сторінку динамічною.
        if set(rule.arguments) - {'lang_code'}:
            continue
        endpoints.add(rule.endpoint)
    return sorted(endpoints)


def fetch_public_pages(app, client):
    """(endpoint, url, html) для кожної публічної сторінки, що віддала 200."""
    from flask import url_for

    with app.test_request_context():
        urls = {ep: url_for(ep) for ep in public_endpoints(app)}

    pages = []
    for endpoint, url in urls.items():
        resp = client.get(url)
        if resp.status_code != 200:
            continue
        pages.append((endpoint, url, resp.data.decode('utf-8')))
    return pages


def jsonld_blocks(html):
    """Розпарсені JSON-LD блоки сторінки. Кидає ValueError на невалідному."""
    raw = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        html, re.DOTALL,
    )
    return [json.loads(chunk) for chunk in raw]


# Поля JSON-LD, у яких Google очікує абсолютний URL.
URL_KEYS = ('image', 'logo', 'item', 'url')


def iter_url_values(node):
    """Пари (ключ, значення) для URL-полів усередині JSON-LD, рекурсивно."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in URL_KEYS:
                if isinstance(value, str):
                    yield key, value
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            yield key, item
            yield from iter_url_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_url_values(item)
