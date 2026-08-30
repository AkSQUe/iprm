"""Сторожі абсолютності URL у структурованих даних, набору hreflang і
закритості приватних розділів."""
import re

from flask import url_for
from flask_babel import refresh

from app.i18n import (
    DEFAULT_LANGUAGE, LANGUAGES, OG_LOCALES, PREFIXED_LANGUAGES,
)
from tests.test_seo.helpers import (
    LOCALE_PASSES, fetch_public_pages, find_nodes_by_type, is_absolute_url,
    iter_url_values, jsonld_blocks, organization_ids, pass_label, provider_ids,
    rendered_lang,
)


def _pages_by_locale(app):
    """[(мітка локалі, ендпоінт, url, html)] по всіх прогонах.

    Твердження нижче довго дивились ЛИШЕ на український рендер:
    fetch_public_pages() кликали без локалі, тож JSON-LD і hreflang на
    /ru/ та /en/ не оглядав жоден сторож. Саме тому регресію перекладу
    назви організації (Задача B, T4) не спіймало б ніщо -- вона видима
    рівно на тих сторінках, яких ніхто не читав.
    """
    for lang in LOCALE_PASSES:
        label = pass_label(lang)
        for endpoint, url, html in fetch_public_pages(app, lang=lang)[0]:
            yield label, endpoint, url, html


class TestSchemaUrls:
    def test_schema_urls_absolute(self, app):
        bad = []
        for label, endpoint, _url, html in _pages_by_locale(app):
            for block in jsonld_blocks(html):
                for key, value in iter_url_values(block):
                    if not is_absolute_url(value):
                        bad.append(f'{endpoint} [{label}]: {key} = {value}')
        assert not bad, (
            'Відносні URL у структурованих даних:\n' + '\n'.join(bad)
        )


class TestOrganizationIdIsLocaleIndependent:
    """@id організації -- ОДИН рядок на весь сайт, у всіх трьох локалях.

    Доти, доки він будувався з url_for('main.index', _external=True), він
    ішов за активною мовою: '/#org', '/ru/#org', '/en/#org'. Для Google
    @id -- це ідентичність сутності, тож одна компанія оголошувалась
    трьома різними організаціями, а provider курсу з /ru/ вказував на
    третю з них замість тієї, що описана на українській версії.

    Твердження навмисно не називає очікуваного рядка: воно вимагає
    ЗБІГУ між локалями й між посиланнями. Дослівне значення -- справа
    шаблонів, а не сторожа; сторож ловить розходження.
    """

    def test_all_pages_and_locales_agree_on_one_organization_id(self, app):
        seen = {}
        for label, endpoint, _url, html in _pages_by_locale(app):
            blocks = jsonld_blocks(html)
            ids = organization_ids(blocks) | set(provider_ids(blocks))
            assert ids, f'{endpoint} [{label}]: жодного @id організації'
            for value in ids:
                seen.setdefault(value, []).append(f'{endpoint} [{label}]')
        assert len(seen) == 1, (
            'Організація оголошена більш ніж одним @id -- для Google це '
            'різні сутності:\n' + '\n'.join(
                f'{value}: {sorted(where)}' for value, where in sorted(seen.items())
            )
        )

    def test_the_canonical_id_has_no_language_prefix(self, app):
        """Друга половина: збіг сам по собі виконався б і на трьох
        однаково НЕправильних значеннях -- наприклад, якби всі сторінки
        разом почали віддавати '/ru/#org'. Канонічним є безпрефіксний
        корінь мови-джерела, бо саме він не міняється при зміні
        дефолтної локалі відвідувача."""
        with app.test_request_context():
            expected = url_for(
                'main.index', lang_code=DEFAULT_LANGUAGE, _external=True,
            ) + '#org'
        bad = []
        for label, endpoint, _url, html in _pages_by_locale(app):
            blocks = jsonld_blocks(html)
            for value in organization_ids(blocks) | set(provider_ids(blocks)):
                if value != expected:
                    bad.append(f'{endpoint} [{label}]: {value!r}')
        assert not bad, (
            f'@id організації не дорівнює канонічному {expected!r}:\n'
            + '\n'.join(bad)
        )


class TestContactPageIsOneEntity:
    """mainEntity на /contact -- та сама організація, що й #org.

    Вузол довго не мав @id взагалі, тож Google читав його як ДРУГУ
    організацію поруч із #org із base.html: дві сутності з тим самим
    телефоном і тими самими назвами. Спільний @id зшиває їх в одну, у
    якій контактні дані доповнюють загальні.

    Твердження окреме від сусіднього класу невипадково: organization_ids()
    збирає лише вузли, що @id МАЮТЬ, тож зникнення @id з mainEntity для
    нього невидиме -- вузол просто випадає з вибірки. Ця перевірка
    заходить із іншого боку: бере ContactPage і вимагає @id від того, що
    в ньому оголошено головною сутністю.
    """

    def test_main_entity_carries_the_canonical_organization_id(self, app):
        with app.test_request_context():
            expected = url_for(
                'main.index', lang_code=DEFAULT_LANGUAGE, _external=True,
            ) + '#org'
        bad = []
        client = app.test_client()
        for lang in LOCALE_PASSES:
            label = pass_label(lang)
            refresh()
            resp = client.get(f'/{lang}/contact' if lang else '/contact')
            assert resp.status_code == 200
            blocks = jsonld_blocks(resp.data.decode('utf-8'))
            pages = find_nodes_by_type(blocks, 'ContactPage')
            assert len(pages) == 1, f'[{label}] ContactPage: {len(pages)}'
            entity = pages[0].get('mainEntity')
            assert isinstance(entity, dict), (
                f'[{label}] ContactPage без mainEntity-обʼєкта: {entity!r}'
            )
            if entity.get('@id') != expected:
                bad.append(
                    f'[{label}] mainEntity.@id = {entity.get("@id")!r}, '
                    f'очікували {expected!r}'
                )
        assert not bad, (
            'mainEntity на /contact -- окрема сутність, а не #org:\n'
            + '\n'.join(bad)
        )


class TestHreflang:
    def test_localized_pages_list_all_languages(self, app):
        # Очікування виводимо з is_endpoint_expecting -- того самого
        # предиката, яким керується _hreflang_alternates() -- а не зі
        # списку локалізованих ендпоінтів, підтримуваного руками (він би
        # розходився з реальністю). Сторінка, що втратила alternates через
        # проковтнуте в i18n.py виключення, тепер падає, а не мовчки
        # пропускається порожнім набором.
        #
        # Набір мусить бути ОДНАКОВИЙ у всіх трьох рендерах: hreflang --
        # це взаємні посилання, і /ru/, що не назвав en, розриває групу.
        expected = set(LANGUAGES) | {'x-default'}
        bad = []
        for label, endpoint, _url, html in _pages_by_locale(app):
            langs = set(re.findall(
                r'<link rel="alternate" hreflang="([^"]+)"', html,
            ))
            localized = app.url_map.is_endpoint_expecting(
                endpoint, 'lang_code',
            )
            if localized:
                if langs != expected:
                    bad.append(
                        f'{endpoint} [{label}]: очікували {sorted(expected)}, '
                        f'отримали {sorted(langs)}'
                    )
            elif langs:
                bad.append(
                    f'{endpoint} [{label}]: hreflang не очікувався, отримали '
                    f'{sorted(langs)}'
                )
        assert not bad, (
            f'Невідповідність hreflang очікуваному {sorted(expected)}:\n'
            + '\n'.join(bad)
        )

    def test_hreflang_urls_absolute(self, app):
        bad = []
        for label, endpoint, _url, html in _pages_by_locale(app):
            for href in re.findall(
                r'<link rel="alternate" hreflang="[^"]+" href="([^"]+)"', html,
            ):
                if not is_absolute_url(href):
                    bad.append(f'{endpoint} [{label}]: {href}')
        assert not bad, 'Відносні hreflang:\n' + '\n'.join(bad)


class TestDeclaredLanguageMatchesContent:
    """<html lang> і og:locale описують ВМІСТ, а не сесію відвідувача.

    П'ять юридичних сторінок (/cookies, /disclaimer, /offer, /privacy,
    /refund) мовного префікса не мають узагалі -- /ru/privacy не існує і
    віддає 404, -- а в їхніх текстах немає жодного виклику перекладу.
    Але рендеряться вони під base.html, який брав мову з current_lang,
    тобто з СЕСІЇ: досить було зайти на /ru/, щоб /privacy оголосив
    lang="ru" над суцільно українською офертою. Хибна заява і для
    краулера (мовний таргетинг видачі), і для скрінрідера (вибір
    голосового рушія).

    Сторожі вибірки цього не бачили за конструкцією: юридичні сторінки
    живуть лише в українському прогоні, де очікування й так 'uk'. Тому
    перевірка окрема й ходить саме тим шляхом, яким ходить відвідувач --
    спершу на локалізовану сторінку, потім на юридичну тим самим
    клієнтом.
    """

    LEGAL_PATHS = ('/cookies', '/disclaimer', '/offer', '/privacy', '/refund')

    def test_untranslated_pages_declare_the_default_language(self, app):
        bad = []
        for lang in PREFIXED_LANGUAGES:
            client = app.test_client()
            refresh()
            assert client.get(f'/{lang}/').status_code == 200
            for path in self.LEGAL_PATHS:
                refresh()
                resp = client.get(path)
                assert resp.status_code == 200, f'{path}: {resp.status_code}'
                html = resp.data.decode('utf-8')
                actual = rendered_lang(html)
                if actual != DEFAULT_LANGUAGE:
                    bad.append(
                        f'[сесія {lang}] {path}: <html lang={actual!r}> над '
                        'українським текстом'
                    )
                og = re.search(
                    r'<meta property="og:locale" content="([^"]*)"', html,
                )
                if not og or og.group(1) != OG_LOCALES[DEFAULT_LANGUAGE]:
                    bad.append(
                        f'[сесія {lang}] {path}: og:locale = '
                        f'{og.group(1) if og else None!r}, очікували '
                        f'{OG_LOCALES[DEFAULT_LANGUAGE]!r}'
                    )
        assert not bad, (
            'Сторінки оголошують не ту мову, якою написані:\n' + '\n'.join(bad)
        )

    def test_localized_pages_still_follow_the_session_locale(self, app):
        """Друга половина: правило не мусить З'ЇСТИ мову там, де сторінка
        справді перекладена. Без цього твердження вище проходило б і на
        base.html, що прибив lang="uk" намертво."""
        bad = []
        for lang in PREFIXED_LANGUAGES:
            client = app.test_client()
            for path in (f'/{lang}/', f'/{lang}/contact', f'/{lang}/courses/'):
                refresh()
                resp = client.get(path)
                assert resp.status_code == 200, f'{path}: {resp.status_code}'
                html = resp.data.decode('utf-8')
                actual = rendered_lang(html)
                if actual != lang:
                    bad.append(f'{path}: <html lang={actual!r}>')
                og = re.search(
                    r'<meta property="og:locale" content="([^"]*)"', html,
                )
                if not og or og.group(1) != OG_LOCALES[lang]:
                    bad.append(
                        f'{path}: og:locale = '
                        f'{og.group(1) if og else None!r}, очікували '
                        f'{OG_LOCALES[lang]!r}'
                    )
        assert not bad, (
            'Локалізовані сторінки перестали оголошувати свою мову:\n'
            + '\n'.join(bad)
        )


class TestPrivatePagesClosed:
    # Голий шлях блюпринта ("/registration/", "/quiz/") не матчить жодного
    # маршруту -- усі вони вимагають параметр -- тож 404 віддає дефолтний
    # обробник Flask ДО диспетчеризації, і after_request, зареєстрований
    # на блюпринті, не встигає спрацювати. Це нічого не довело б про сам
    # блюпринт. Тому беремо шляхи, що справді туди потрапляють (штучні id,
    # яких немає в БД) -- after_request виконується навіть коли view падає
    # у 404 чи редіректить на логін.
    def test_private_blueprints_send_noindex_header(self, client):
        for path in (
            '/auth/login',
            '/registration/999999/register',
            '/quiz/999999',
        ):
            resp = client.get(path, follow_redirects=False)
            header = resp.headers.get('X-Robots-Tag', '')
            assert 'noindex' in header, f'{path}: X-Robots-Tag = {header!r}'

    def test_404_page_is_closed_to_indexing(self, client):
        resp = client.get('/definitely-not-a-real-page', follow_redirects=False)
        assert resp.status_code == 404
        body = resp.data.decode('utf-8')
        assert 'name="robots"' in body and 'noindex' in body
