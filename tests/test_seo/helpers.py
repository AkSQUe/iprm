"""Спільні хелпери SEO-сторожів: перелік публічних сторінок і список
відомого боргу."""
import json
import re
from html.parser import HTMLParser

from flask_babel import refresh

from app.i18n import DEFAULT_LANGUAGE, PREFIXED_LANGUAGES

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
# сторінок: ендпоінт -> (очікуваний код, причина).
#
# Без цього словника fetch_public_pages() мовчки викидала будь-яку
# сторінку, що перестала віддавати 200, і всі структурні сторожі лишались
# зеленими над меншим набором. Перевірено мутацією: підміна в'ю
# clinics.clinic_list на abort(500) не валила ЖОДНОГО з 28 тестів -- лише
# прискорювала прогін. Тепер набір пропущених звіряється з цим словником
# на рівність: сторінка, що зламалась, валить сюїту, а нова навмисна
# не-HTML відповідь вимагає іменованого запису -- та сама дисципліна
# "виняток завжди іменований", що й у LENGTH_EXCEPTIONS.
#
# Значення довго було голою прозою: рядок називав код у тексті, але його
# ніхто не звіряв із фактичною відповіддю. Перевірено мутацією: підміна
# main.design_system на abort(500) (замість документованого 302) лишала
# сюїту зеленою -- набір пропущених ключів не змінюється, а саме число
# всередині рядка ніхто не читав. Тепер код -- окреме машинозчитуване поле,
# і test_page_seo.py звіряє його з фактичним skipped[endpoint].
EXPECTED_NON_200 = {
    'main.design_system': (302,
        '302 -- каталог дизайн-системи під admin_required: анонімного '
        'відвідувача редіректить на логін. Сторінка службова, в індекс не '
        'йде, публічних SEO-тверджень до неї не застосовуємо.'
    ),
    'main.legacy_account': (301,
        '301 -- історичний /account лишений як постійний редірект на '
        'особистий кабінет. Власного HTML не має за визначенням.'
    ),
    'i18n_uk_root': (301,
        '301 -- /uk/ канонізується в безпрефіксний корінь (українська, '
        'мова-джерело, живе без префікса). Редірект тут і є правильною '
        'поведінкою, окремої сторінки не існує.'
    ),
    'meta_leads.verify_subscription': (403,
        '403 -- верифікаційний вебхук Meta Lead Ads: без правильних '
        'hub.mode/hub.verify_token відповідає відмовою. Це точка '
        'інтеграції, що віддає plain text, а не сторінка.'
    ),
    # Партнерське JSON-API (X-API-Key). Віддає 404, поки інтеграцію
    # вимкнено -- навмисно, щоб не підтверджувати існування ендпоінта
    # (див. require_api_key у app/api/v1/auth.py). HTML не віддає в
    # жодному зі станів.
    'api_v1.list_events': (404, '404 -- партнерське JSON-API, інтеграцію вимкнено.'),
    'api_v1.list_leads': (404, '404 -- партнерське JSON-API, інтеграцію вимкнено.'),
    'api_v1.list_online_courses': (404, '404 -- партнерське JSON-API, інтеграцію вимкнено.'),
    'api_v1.list_online_enrollments': (404, '404 -- партнерське JSON-API, інтеграцію вимкнено.'),
    'api_v1.list_participants': (404, '404 -- партнерське JSON-API, інтеграцію вимкнено.'),
    'api_v1.list_registrations': (404, '404 -- партнерське JSON-API, інтеграцію вимкнено.'),
    'api_v1.list_specializations': (404, '404 -- партнерське JSON-API, інтеграцію вимкнено.'),
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


# Прогони по локалях. None -- українська без префікса: саме так її віддає
# прод, і саме в цьому прогоні живуть нелокалізовані сторінки.
#
# lang='uk' тут навмисно НЕ вживається: із заданою локаллю вибірка
# звужується до локалізованих ендпоінтів, і п'ять сторінок без префікса
# (/cookies, /disclaimer, /offer, /privacy, /refund) не потрапили б у
# жоден прогін узагалі.
LOCALE_PASSES = [None] + PREFIXED_LANGUAGES


def pass_label(lang):
    """Ім'я локалі для повідомлень і ключів: None -> 'uk'."""
    return lang or DEFAULT_LANGUAGE


def public_urls(app, lang=None):
    """Ендпоінт -> URL публічної сторінки (за потреби -- у заданій локалі).

    Із ЗАДАНОЮ локаллю повертає лише локалізовані ендпоінти. П'ять
    публічних сторінок мовного префікса не мають узагалі, і url_for
    віддавав для них той самий непрефіксований шлях у всіх трьох
    прогонах: /cookies міряли як uk, як ru і як en -- двадцять вимірів
    над рендером, якого прод у цих локалях не віддає. Предикат той
    самий, яким керується _hreflang_alternates() у app/i18n.py.
    """
    from flask import url_for

    urls = {}
    with app.test_request_context():
        for endpoint in public_endpoints(app):
            localized = app.url_map.is_endpoint_expecting(endpoint, 'lang_code')
            if lang and not localized:
                continue
            if lang and localized:
                urls[endpoint] = url_for(endpoint, lang_code=lang)
            else:
                urls[endpoint] = url_for(endpoint)
    return urls


# Ядро публічних сторінок: їхнє зникнення -- регресія, а не зміна набору.
#
# Звірка вибірки з очікуванням (expected_pass_sets) ловить "сторінка
# перестала віддавати 200", але НЕ ловить "роут видалено чи
# перейменовано": і очікування, і сама вибірка виводяться з url_map, тож
# при зникненні роуту обидві множини худнуть РАЗОМ і далі збігаються.
# Доведено мутацією: підміна public_endpoints() так, щоб вона викидала
# trainers.trainer_list, лишала всю сюїту зеленою -- сторінка тренерів
# просто переставала існувати для сторожів. MIN_PAGES_PER_PASS від цього
# не рятує: він спрацьовує лише на обвалі набору, а не на втраті однієї
# сторінки.
#
# Тому набір, який мусить бути публічним ЗАВЖДИ, названо тут явно. Це не
# дублікат вибірки: вибірка описує "що є", а цей список -- "що не має
# права зникнути". Сюди входять сторінки, зникнення яких означало б
# втрату входу в цілий розділ сайту (головна, каталоги очних і онлайн
# курсів, тренери, клініки, блог, контакти, лабораторії) і п'ять
# юридичних сторінок, обов'язкових для торгівлі й для платіжних систем.
#
# Динамічні сторінки (курс, тренер, допис) сюди не входять -- вони
# потребують рядків у БД і живуть у test_dynamic_pages.py.
CORE_PUBLIC_ENDPOINTS = frozenset({
    'main.index',
    'main.contact',
    'main.labs',
    'courses.course_list',
    'online.course_list',
    'trainers.trainer_list',
    'clinics.clinic_list',
    'blog.index',
    'main.cookies',
    'main.disclaimer',
    'main.offer',
    'main.privacy',
    'main.refund',
})


# Підлога розміру вибірки для КОЖНОГО прогону локалі.
#
# Очікуваний набір сторінок нижче виводиться з url_map, а не з рукописного
# списку -- це добре (він не може застаріти), але й небезпечно: якби
# public_urls() колись повернула порожньо, очікування теж стало б
# порожнім, звірка множин зійшлася б на двох порожніх множинах, і всі
# сторожі проходили б над нічим. Поріг нижчий за поточні 15/10/10
# навмисно: точну звірку робить сама рівність множин, а це -- запобіжник
# проти вакууму, а не її дублікат.
MIN_PAGES_PER_PASS = 8


def expected_pass_sets(app, lang=None):
    """(очікувані 200, очікувані не-200 з кодами) для прогону локалі.

    Виводиться з url_map і EXPECTED_NON_200, а не з окремого рукописного
    списку на кожну локаль -- такий список розійшовся б із реальністю
    першої ж миті. Ендпоінт із EXPECTED_NON_200 потрапляє в очікувані
    пропущені лише тоді, коли він узагалі є в цьому прогоні: у прогонах
    ru/en вибірка звужена до локалізованих сторінок, тож /uk/,
    /design-system і партнерське API там не з'являються ні як 200, ні як
    пропущені.
    """
    urls = public_urls(app, lang)
    skipped = {
        endpoint: code
        for endpoint, (code, _why) in EXPECTED_NON_200.items()
        if endpoint in urls
    }
    return set(urls) - set(skipped), skipped


class _H1Counter(HTMLParser):
    """Лічильник <h1> у РОЗМІТЦІ, а не в тексті сторінки.

    Регексп `<h1[\\s>]` над сирим HTML рахував і те, що розміткою не є:
    рядок "<h1" усередині inline-скрипта, JSON-рядка (наприклад, у блоці
    JSON-LD чи в даних редактора) або HTML-коментаря додавав сторінці
    неіснуючий заголовок. Помилка тиха в обидва боки: вона однаково легко
    зробила б із однієї правильної <h1> дві "зайві" й приховала б
    сторінку, що втратила заголовок насправді.

    HTMLParser віддає вміст <script> і <style> як дані (CDATA-режим), а не
    як теґи, тож підрахунок стартових теґів h1 сам по собі не бачить
    нічого, що всередині них написано. Стандартна бібліотека -- нової
    залежності не з'являється.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'h1':
            self.count += 1


def count_h1(html):
    """Скільки справжніх <h1> на сторінці."""
    parser = _H1Counter()
    parser.feed(html)
    parser.close()
    return parser.count


def rendered_lang(html):
    """Значення lang у <html> -- мова, якою сторінка себе оголосила.

    base.html бере його з content_lang -- це current_lang
    (str(flask_babel.get_locale()), app/i18n.py, inject_i18n) для всього,
    крім UNTRANSLATED_ENDPOINTS, де вміст існує лише українською і мовою
    рендеру за визначенням є DEFAULT_LANGUAGE.

    Для локалізованих сторінок воно лишається справжнім зондом локалі
    РЕНДЕРУ (а не URL-префікса запиту) -- саме тим, чим і було, коли
    ловило обвал локалі. Для п'яти юридичних сторінок воно тепер
    константа, але зондом воно там і не працювало: ці сторінки живуть
    ЛИШЕ в українському прогоні (мовного префікса не мають), тобто
    очікування там і до цієї зміни було 'uk'.
    """
    found = re.search(r'<html[^>]*\slang="([^"]*)"', html)
    return found.group(1) if found else None


def fetch_public_pages(app, lang=None):
    """(pages, skipped) для публічних сторінок у заданій локалі.

    pages -- список (endpoint, url, html) тих, що віддали 200.
    skipped -- {ендпоінт: код} для решти.

    Раніше функція повертала лише перше і мовчки ковтала друге: зламана
    сторінка просто зникала з вибірки, а сторожі проходили над меншим
    набором, не сказавши й слова. Повертати пропущених окремо -- умова, за
    якої це взагалі можна перевірити (див. TestFetchIsFailClosed).

    Клієнт створюється СВІЙ на кожен виклик, а не береться з фікстури:
    pull_lang_code() робить вибір мови липким через session['lang'], тож
    клієнт, який уже сходив на /ru/..., несе ru у наступний прогін --
    en-прогін міряв би ru-рендер. Це друга, незалежна від кешу babel,
    теча тієї самої діри.

    refresh() -- перед КОЖНИМ запитом, а не раз на прогін. Autouse-фікстура
    db_session (tests/conftest.py) тримає один app context на весь тест, а
    RequestContext.push() перевикористовує вже відкритий контекст того
    самого застосунку -- тож flask_babel віддає локаль, закешовану на
    g._flask_babel ПЕРШИМ запитом, і вся решта вибірки мовчки рендериться
    його мовою. Сьогодні воно виходило правильним лише тому, що sorted()
    випадково ставив локалізований ендпоінт першим.

    Звірка <html lang> -- те, через що обвал локалі більше не пройде
    мовчки. Відтворено мутацією: досить було поставити нелокалізований
    ендпоінт першим у public_endpoints(), щоб прогін uk дав uk, прогін ru
    -- знову uk, а прогін en -- ru, і при цьому
    test_title_and_description_within_targets лишався ЗЕЛЕНИМ: сторожі
    читають html і не мають жодного способу помітити, що він не тією
    мовою.
    """
    expected = pass_label(lang)
    pages = []
    skipped = {}
    client = app.test_client()
    for endpoint, url in public_urls(app, lang).items():
        refresh()
        resp = client.get(url)
        if resp.status_code != 200:
            skipped[endpoint] = resp.status_code
            continue
        html = resp.data.decode('utf-8')
        actual = rendered_lang(html)
        assert actual == expected, (
            f'{endpoint} ({url}): просили локаль {expected!r}, сторінка '
            f'оголосила <html lang={actual!r}>. Це обвал локалі -- усі '
            'твердження над цією вибіркою читали б чужий рендер і '
            'лишались би зеленими.'
        )
        pages.append((endpoint, url, html))
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
#
# sameAs/contentUrl/thumbnailUrl/mainEntityOfPage додані цим раундом:
# main.index уже сьогодні віддає "sameAs" (соцмережі організації з
# SiteSettings -- facebook_url/instagram_url мають непорожні дефолти), а
# blog/post.html -- "mainEntityOfPage". Без цих ключів обидва поля
# лишались повністю поза перевіркою абсолютності.
URL_KEYS = (
    'image', 'logo', 'item', 'url',
    'sameAs', 'contentUrl', 'thumbnailUrl', 'mainEntityOfPage',
)


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


def is_absolute_url(value):
    """Рядок зі справжньою схемою (http:// або https://).

    Раунд 1 фіксу: сторожі скрізь перевіряли `value.startswith('http')` --
    цей рядок приймає й нонсенс на кшталт "httpfoo", бо перевіряє лише
    перші чотири символи, а не наявність реальної схеми з "://". Тепер усі
    місця, де сторожі звіряють абсолютність URL (JSON-LD-поля з
    iter_url_values, canonical, hreflang, Person.url із трейлера), ідуть
    через цю саму функцію -- жодного власного `startswith('http')` більше
    немає ніде в tests/test_seo/.
    """
    return isinstance(value, str) and (
        value.startswith('http://') or value.startswith('https://')
    )


# Типи вузлів JSON-LD, які рахуємо організацією для звірки provider.@id.
ORGANIZATION_TYPES = {'EducationalOrganization', 'Organization'}


def _node_types(node):
    """@type вузла як список -- schema.org дозволяє й голий рядок, і масив
    ("@type": ["Organization", "LocalBusiness"] -- валідний JSON-LD)."""
    node_type = node.get('@type')
    if isinstance(node_type, list):
        return node_type
    return [node_type]


def organization_ids(blocks):
    """Множина @id усіх організаційних вузлів на сторінці (рекурсивно).

    Рекурсія, а не лише верхній рівень блоку/@graph: так само побудований
    iter_url_values, і той самий підхід не пропустить організацію,
    вкладену глибше, ніж сьогоднішні шаблони.

    @type звіряється і як рядок, і як список: `@type in ORGANIZATION_TYPES`
    над списком кидає `TypeError: unhashable type: 'list'` замість
    очікуваного повідомлення про розірване посилання -- сторож і тоді
    фейлив би (крашем, не червоним твердженням), але не тим повідомленням,
    що мало сенс.
    """
    ids = set()

    def _walk(node):
        if isinstance(node, dict):
            if node.get('@id') and any(
                t in ORGANIZATION_TYPES for t in _node_types(node)
            ):
                ids.add(node['@id'])
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    for block in blocks:
        _walk(block)
    return ids


def _reference_ids(value):
    """@id-подібні значення з value: dict-посилання ({'@id': ...}), голий
    рядок-IRI (валідне JSON-LD скорочення того самого) або список будь-якої
    суміші двох форм.

    provider -- не обов'язково один dict: schema.org дозволяє й масив
    провайдерів, і скорочену форму "provider": "https://...#org" без
    обгортки в об'єкт. Стара версія приймала лише перше -- масив чи голий
    рядок мовчки давали [] і перевірка проходила вакуумно (fail open),
    хоч жодна сторінка сьогодні так не робить.
    """
    if isinstance(value, dict):
        return [value['@id']] if '@id' in value else []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        ids = []
        for item in value:
            ids.extend(_reference_ids(item))
        return ids
    return []


def provider_ids(blocks):
    """Значення provider['@id'] з усіх вузлів на сторінці (рекурсивно)."""
    ids = []

    def _walk(node):
        if isinstance(node, dict):
            if 'provider' in node:
                ids.extend(_reference_ids(node['provider']))
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    for block in blocks:
        _walk(block)
    return ids


def find_nodes_by_type(blocks, type_name):
    """Усі вузли з @type == type_name на сторінці (рекурсивно, і рядок,
    і масив @type -- див. _node_types)."""
    found = []

    def _walk(node):
        if isinstance(node, dict):
            if type_name in _node_types(node):
                found.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    for block in blocks:
        _walk(block)
    return found


def head_field(html, field):
    """Довжина title/description сторінки або None, якщо тега немає."""
    if field == 'title':
        found = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
    else:
        found = re.search(r'<meta name="description" content="([^"]*)"', html)
    return found.group(1).strip() if found else None
