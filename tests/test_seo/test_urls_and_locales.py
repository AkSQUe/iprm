"""Сторожі абсолютності URL у структурованих даних, набору hreflang і
закритості приватних розділів."""
import re

from flask import url_for
from flask_babel import refresh

from app.i18n import (
    DEFAULT_LANGUAGE, LANGUAGES, OG_LOCALES, PREFIXED_LANGUAGES,
    UNTRANSLATED_ENDPOINTS,
)
from tests.test_seo.helpers import (
    LOCALE_PASSES, content_translation_calls, fetch_public_pages,
    find_nodes_by_type, is_absolute_url, iter_url_values, jsonld_blocks,
    organization_ids, pass_label, public_urls, reference_ids, rendered_lang,
    templates_named_in_view, templates_rendered_by,
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

    Посилання беруться через reference_ids (provider, publisher, author),
    а не через provider_ids: publisher і author не читав жоден хелпер, і
    відкат `'publisher': {'@id': org_id()}` на головній до
    локале-залежного `_home ~ '#org'` проходив зеленим -- WebSite починав
    вказувати на організацію, якої на сторінці немає.
    """

    def test_all_pages_and_locales_agree_on_one_organization_id(self, app):
        seen = {}
        for label, endpoint, _url, html in _pages_by_locale(app):
            blocks = jsonld_blocks(html)
            ids = organization_ids(blocks) | set(reference_ids(blocks))
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
            for value in organization_ids(blocks) | set(reference_ids(blocks)):
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

    def _paths(self, app):
        """Шляхи сторінок із UNTRANSLATED_ENDPOINTS.

        Виводяться з самої константи, а не переліком: другий рукописний
        список звіряв би константу лише з її ж копією -- і те, і те
        доводилось би правити руками, а розійтися вони могли мовчки.
        """
        with app.test_request_context():
            return sorted(
                url_for(endpoint) for endpoint in UNTRANSLATED_ENDPOINTS
            )

    def test_untranslated_pages_declare_the_default_language(self, app):
        paths = self._paths(app)
        assert paths, 'UNTRANSLATED_ENDPOINTS порожній -- перевіряти нічого'
        bad = []
        for lang in PREFIXED_LANGUAGES:
            client = app.test_client()
            refresh()
            assert client.get(f'/{lang}/').status_code == 200
            for path in paths:
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


class TestUntranslatedConstantIsDerivable:
    """UNTRANSLATED_ENDPOINTS мусить збігатися з тим, що видно в розмітці.

    Константа керує тим, яку мову сторінка оголошує світові, і доти, доки
    вона звірялась лише сама із собою, небезпечний напрямок дрейфу був
    відкритий навстіж. Доведено мутацією: додавання payments.success і
    payments.failure лишало сюїту зеленою -- тобто дві повністю
    перекладені сторінки мовчки почали б оголошувати себе українськими,
    рівно та брехня, заради уникнення якої список і став іменованим.
    Протилежні напрямки ловились: додавання локалізованого ендпоінта --
    дванадцятьма падіннями, видалення юридичного -- одним.

    Істина виводиться з розмітки: скільки викликів перекладу в
    {% block content %} шаблона, який ендпоінт справді рендерить.
    Розділення чисте й без сірої зони -- 0 у п'яти юридичних сторінок,
    3 і більше в будь-якого іншого кандидата.
    """

    def _templates_for(self, app, client, endpoint, url):
        """(шаблони, як їх здобули) для ендпоінта.

        Основний шлях -- сигнал template_rendered на справжньому запиті.
        Запасний -- render_template(...) у вихідному коді в'ю: під
        @login_required (payments.success) анонімний GET віддає редірект і
        не рендерить нічого, а запис у константі перевірити все одно
        треба -- і назвати справжню причину відмови, а не "не змогли".
        """
        if url is not None:
            status, names = templates_rendered_by(app, client, url)
            if status == 200 and names:
                return names, f'рендер {url} ({status})'
        names = templates_named_in_view(app, endpoint)
        if names:
            return names, 'render_template у коді в\'ю'
        return [], 'ні рендером, ні читанням коду в\'ю'

    def test_every_listed_endpoint_renders_untranslated_content(self, app):
        """Небезпечний напрямок: у списку не має бути перекладеної сторінки."""
        client = app.test_client()
        bad = []
        with app.test_request_context():
            urls = {}
            for endpoint in UNTRANSLATED_ENDPOINTS:
                try:
                    urls[endpoint] = url_for(endpoint)
                except Exception:
                    urls[endpoint] = None
        for endpoint in sorted(UNTRANSLATED_ENDPOINTS):
            names, how = self._templates_for(app, client, endpoint, urls[endpoint])
            if not names:
                bad.append(
                    f'{endpoint}: шаблон не знайдено ({how}) -- запис '
                    'неперевірний, а неперевірному тут не місце'
                )
                continue
            for name in names:
                calls = content_translation_calls(app, name)
                if calls is None:
                    bad.append(
                        f'{endpoint} ({name}): немає {{% block content %}} -- '
                        'перевірити вміст цим способом не можна'
                    )
                elif calls:
                    bad.append(
                        f'{endpoint} ({name}): {calls} викликів перекладу в '
                        'основному вмісті -- сторінка перекладена, і '
                        'оголошувати її українською означає брехати '
                        'краулеру й скрінрідеру'
                    )
        assert not bad, (
            'UNTRANSLATED_ENDPOINTS містить те, що українським не є:\n'
            + '\n'.join(bad)
        )

    def test_no_untranslated_public_page_is_missing_from_the_list(self, app):
        """Зворотний напрямок, у межах публічних сторінок.

        Кандидати -- ті самі публічні HTML-сторінки, якими ходять решта
        сторожів. Нова сторінка з українським-лише вмістом мусить або
        потрапити в список, або отримати переклад: мовчки лишитись із
        оголошеною мовою сесії вона не має права.
        """
        client = app.test_client()
        derived = set()
        unverifiable = []
        candidates = public_urls(app)
        for endpoint, url in sorted(candidates.items()):
            status, names = templates_rendered_by(app, client, url)
            if status != 200 or not names:
                continue  # не HTML-сторінка; це стереже TestFetchIsFailClosed
            calls = [content_translation_calls(app, name) for name in names]
            if any(c is None for c in calls):
                unverifiable.append(f'{endpoint}: {names}')
            elif not any(calls):
                derived.add(endpoint)
        assert not unverifiable, (
            'Публічні сторінки без {% block content %} -- перевірити мову '
            'їхнього вмісту нічим:\n' + '\n'.join(unverifiable)
        )
        listed = UNTRANSLATED_ENDPOINTS & set(candidates)
        assert derived == listed, (
            'Список українських-лише сторінок розійшовся з розміткою.\n'
            f'У розмітці українські, але не в списку: {sorted(derived - listed)}\n'
            f'У списку, але вміст перекладений: {sorted(listed - derived)}'
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
