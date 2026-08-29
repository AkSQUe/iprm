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

# Ендпоінти, що навмисно не віддають 200 і тому не потрапляють у вибірку
# сторінок: ендпоінт -> причина.
#
# Без цього словника fetch_public_pages() мовчки викидала будь-яку
# сторінку, що перестала віддавати 200, і всі структурні сторожі лишались
# зеленими над меншим набором. Перевірено мутацією: підміна в'ю
# clinics.clinic_list на abort(500) не валила ЖОДНОГО з 28 тестів -- лише
# прискорювала прогін. Тепер набір пропущених звіряється з цим словником
# на рівність: сторінка, що зламалась, валить сюїту, а нова навмисна
# не-HTML відповідь вимагає іменованого запису -- та сама дисципліна
# "виняток завжди іменований", що й у LENGTH_EXCEPTIONS.
EXPECTED_NON_200 = {
    'main.design_system': (
        '302 -- каталог дизайн-системи під admin_required: анонімного '
        'відвідувача редіректить на логін. Сторінка службова, в індекс не '
        'йде, публічних SEO-тверджень до неї не застосовуємо.'
    ),
    'main.legacy_account': (
        '301 -- історичний /account лишений як постійний редірект на '
        'особистий кабінет. Власного HTML не має за визначенням.'
    ),
    'i18n_uk_root': (
        '301 -- /uk/ канонізується в безпрефіксний корінь (українська, '
        'мова-джерело, живе без префікса). Редірект тут і є правильною '
        'поведінкою, окремої сторінки не існує.'
    ),
    'meta_leads.verify_subscription': (
        '403 -- верифікаційний вебхук Meta Lead Ads: без правильних '
        'hub.mode/hub.verify_token відповідає відмовою. Це точка '
        'інтеграції, що віддає plain text, а не сторінка.'
    ),
    # Партнерське JSON-API (X-API-Key). Віддає 404, поки інтеграцію
    # вимкнено -- навмисно, щоб не підтверджувати існування ендпоінта
    # (див. require_api_key у app/api/v1/auth.py). HTML не віддає в
    # жодному зі станів.
    'api_v1.list_events': '404 -- партнерське JSON-API, інтеграцію вимкнено.',
    'api_v1.list_leads': '404 -- партнерське JSON-API, інтеграцію вимкнено.',
    'api_v1.list_online_courses': '404 -- партнерське JSON-API, інтеграцію вимкнено.',
    'api_v1.list_online_enrollments': '404 -- партнерське JSON-API, інтеграцію вимкнено.',
    'api_v1.list_participants': '404 -- партнерське JSON-API, інтеграцію вимкнено.',
    'api_v1.list_registrations': '404 -- партнерське JSON-API, інтеграцію вимкнено.',
    'api_v1.list_specializations': '404 -- партнерське JSON-API, інтеграцію вимкнено.',
}

# Цільові межі довжин зі специфікації.
TITLE_MIN, TITLE_MAX = 30, 60
DESC_MIN, DESC_MAX = 120, 160

_BLOG_INDEX_DESC = (
    'блог наповнюється редакційно і на момент написання порожній: жодної '
    'конкретної теми (курси, дослідження, терапії) додати в опис чесно не '
    'можна -- це були б непідтверджені заяви про вміст, якого ще немає. '
    'Розширити без конкретики означало б штучно заповнити текст словами '
    'заради довжини, а не описати сторінку -- тому лишається винятком, а '
    'не переписом.'
)

_PREEXISTING = (
    'борг, старший за цей план: рядок написаний до нього і ним не '
    'вводився. Переписувати чужий маркетинговий текст -- поза межами '
    'задачі, тому запис іменований, а не пом\'якшена межа.'
)

# Сторінки, чию довжину не виправити без рішення про контент:
# (ендпоінт, локаль, поле) -> причина. Межі НЕ пом'якшуються -- виняток
# завжди іменований.
#
# Ключ став тривимірним у цьому раунді. До нього виняток був
# per-endpoint: він прощав title і description одразу і в усіх трьох
# локалях -- тобто рівно те, чого ніхто не оглядав. Сама ж перевірка
# довжин бачила лише український рендер, тож ru/en виходили за межі
# непоміченими.
LENGTH_EXCEPTIONS = {
    ('blog.index', 'uk', 'description'): f'description 87 симв. -- {_BLOG_INDEX_DESC}',
    ('blog.index', 'ru', 'description'): f'description 90 симв. -- {_BLOG_INDEX_DESC}',
    ('blog.index', 'en', 'description'): f'description 97 симв. -- {_BLOG_INDEX_DESC}',
    ('main.bpr_documents', 'ru', 'description'): f'description 167 симв. -- {_PREEXISTING}',
    ('main.bpr_documents', 'en', 'description'): f'description 161 симв. -- {_PREEXISTING}',
    ('main.index', 'ru', 'description'): f'description 162 симв. -- {_PREEXISTING}',
    ('main.index', 'en', 'description'): f'description 165 симв. -- {_PREEXISTING}',
}


def public_endpoints(app):
    """Ендпоінти публічних HTML-сторінок без обовʼязкових параметрів.

    Динамічні сторінки (курс, тренер, стаття) сюди не потрапляють -- вони
    потребують рядків у БД і перевіряються окремими тестами з фікстурами
    (tests/test_seo/test_dynamic_pages.py).
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


def public_urls(app, lang=None):
    """Ендпоінт -> URL публічної сторінки (за потреби -- у заданій локалі)."""
    from flask import url_for

    urls = {}
    with app.test_request_context():
        for endpoint in public_endpoints(app):
            if lang and app.url_map.is_endpoint_expecting(endpoint, 'lang_code'):
                urls[endpoint] = url_for(endpoint, lang_code=lang)
            else:
                urls[endpoint] = url_for(endpoint)
    return urls


def fetch_public_pages(app, client, lang=None):
    """(pages, skipped) для публічних сторінок.

    pages -- список (endpoint, url, html) тих, що віддали 200.
    skipped -- {ендпоінт: код} для решти.

    Раніше функція повертала лише перше і мовчки ковтала друге: зламана
    сторінка просто зникала з вибірки, а сторожі проходили над меншим
    набором, не сказавши й слова. Повертати пропущених окремо -- умова, за
    якої це взагалі можна перевірити (див. TestFetchIsFailClosed).
    """
    pages = []
    skipped = {}
    for endpoint, url in public_urls(app, lang).items():
        resp = client.get(url)
        if resp.status_code != 200:
            skipped[endpoint] = resp.status_code
            continue
        pages.append((endpoint, url, resp.data.decode('utf-8')))
    return pages, skipped


def jsonld_blocks(html):
    """Розпарсені JSON-LD блоки сторінки. Кидає ValueError на невалідному.

    Регексп НЕ прив'язаний до дослівного `<script type="...">`: доки він
    вимагав саме такого написання тега, будь-який доданий атрибут (id,
    nonce, data-*) віддавав порожній список -- і ВСІ твердження про
    JSON-LD проходили над порожнечею, лишаючись зеленими. Перевірено
    мутацією: `<script id="org" type="application/ld+json">` у base.html
    не валив жодного з 28 тестів.
    """
    raw = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
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


def head_field(html, field):
    """Довжина title/description сторінки або None, якщо тега немає."""
    if field == 'title':
        found = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
    else:
        found = re.search(r'<meta name="description" content="([^"]*)"', html)
    return found.group(1).strip() if found else None
