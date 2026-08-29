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

# Відомий SEO-борг: ендпоінт -> причина. Кожен запис прибирає Задача 4.
# Тест падає і тоді, коли записаний тут ендпоінт уже проходить перевірку:
# виправив -- прибери запис.
KNOWN_SEO_DEBT = {
    'main.labs': 'title дослівно дублює головну; власний дає Задача 4',
}

# Цільові межі довжин зі специфікації.
TITLE_MIN, TITLE_MAX = 30, 60
DESC_MIN, DESC_MAX = 120, 160

# Сторінки, чию довжину не виправити без рішення про контент: ендпоінт ->
# причина. Межі НЕ пом'якшуються -- виняток завжди іменований. Виміряно на
# першому прогоні сторожа (Задача 1); Задача 4 перепише те, що можна
# переписати без рішення про контент.
LENGTH_EXCEPTIONS = {
    'blog.index': (
        'title 11 симв. -- назва розділу "Блог" коротка за своєю природою; '
        'description 87 симв. -- короткий опис розділу'
    ),
    'clinics.clinic_list': 'description 114 симв. -- короткий опис розділу',
    'courses.course_list': 'description 110 симв. -- короткий опис розділу',
    'main.bpr_documents': (
        'title 20 симв. -- назва розділу "Документи БПР" коротка за своєю '
        'природою'
    ),
    'main.contact': (
        'title 15 симв. -- назва розділу "Контакти" коротша за 30 за своєю '
        'природою; description 108 симв. -- короткий опис розділу'
    ),
    'main.cookies': (
        'title 22 симв. -- назва розділу "Політика Cookie" коротка за '
        'своєю природою; description 109 симв. -- короткий опис розділу'
    ),
    'main.disclaimer': 'description 105 симв. -- короткий опис розділу',
    'main.offer': (
        'title 22 симв. -- назва розділу "Публічна оферта" коротка за '
        'своєю природою; description 117 симв. -- короткий опис розділу'
    ),
    'main.privacy': 'description 98 симв. -- короткий опис розділу',
    'main.refund': 'description 81 симв. -- короткий опис розділу',
    'main.sitemap_page': (
        'title 18 симв. -- назва розділу "Карта сайту" коротка за своєю '
        'природою'
    ),
    'online.course_list': (
        'title 19 симв. -- назва розділу "Онлайн-курси" коротка за своєю '
        'природою; description 107 симв. -- короткий опис розділу'
    ),
    'trainers.trainer_list': (
        'title 24 симв. -- назва розділу "Тренери інституту" коротка за '
        'своєю природою; description 110 симв. -- короткий опис розділу'
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
