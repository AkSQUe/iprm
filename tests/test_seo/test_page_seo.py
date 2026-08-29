"""Сторожі публічних сторінок: заголовок, canonical, опис, валідність
структурованих даних."""
import re

from flask_babel import refresh

from app.i18n import LANGUAGES
from tests.test_seo.helpers import (
    DESC_MAX, DESC_MIN, EXPECTED_NON_200, KNOWN_SEO_DEBT, LENGTH_EXCEPTIONS,
    TITLE_MAX, TITLE_MIN, fetch_public_pages, head_field, is_absolute_url,
    jsonld_blocks,
)


class TestFetchIsFailClosed:
    """Вибірка сторінок мусить падати, а не худнути.

    Доти, доки fetch_public_pages() мовчки пропускала все, що не 200,
    зламана сторінка просто зникала з набору: `abort(500)` у
    clinics.clinic_list лишав усі вісім структурних сторожів зеленими
    (і прогін швидшим). Єдине, що це ловить, -- звірка набору пропущених
    із іменованим списком.
    """

    def test_skipped_set_matches_named_constant(self, app, client):
        _, skipped = fetch_public_pages(app, client)
        assert set(skipped) == set(EXPECTED_NON_200), (
            'Набір сторінок поза вибіркою розійшовся з EXPECTED_NON_200.\n'
            f'Зайві (сторінка перестала віддавати 200): '
            f'{ {ep: skipped[ep] for ep in set(skipped) - set(EXPECTED_NON_200)} }\n'
            f'Застарілі (сторінка знову віддає 200, прибери запис): '
            f'{sorted(set(EXPECTED_NON_200) - set(skipped))}'
        )

    def test_skipped_status_matches_documented_code(self, app, client):
        """Ключ EXPECTED_NON_200 звірявся лише як МНОЖИНА -- сам код
        усередині причини був прозою, яку ніхто не читав. Доведено
        мутацією: підміна в'ю main.design_system на abort(500) замість
        задокументованого 302 лишала сюїту зеленою -- набір пропущених
        ключів не міняється, лише число під ключем."""
        _, skipped = fetch_public_pages(app, client)
        bad = []
        for endpoint, actual_code in skipped.items():
            if endpoint not in EXPECTED_NON_200:
                continue  # test_skipped_set_matches_named_constant це вже ловить
            expected_code, _reason = EXPECTED_NON_200[endpoint]
            if actual_code != expected_code:
                bad.append(
                    f'{endpoint}: задокументовано {expected_code}, '
                    f'фактично {actual_code}'
                )
        assert not bad, (
            'Фактичний код розійшовся з задокументованим у '
            'EXPECTED_NON_200:\n' + '\n'.join(bad)
        )

    def test_every_expected_exception_has_a_reason(self):
        empty = [
            ep for ep, (code, why) in EXPECTED_NON_200.items()
            if not (why or '').strip()
        ]
        assert not empty, f'Записи без причини: {empty}'

    def test_selection_is_not_empty(self, app, client):
        pages, _ = fetch_public_pages(app, client)
        # Поріг навмисно нижчий за поточні 15: точну звірку набору робить
        # тест вище, а цей лишається підлогою здорового глузду -- він має
        # спрацювати, якщо вибірка обвалиться, а не дублювати сусіда.
        assert len(pages) >= 10, (
            f'У вибірці лишилось {len(pages)} сторінок -- надто мало, '
            'щоб твердження нижче щось означали.'
        )


class TestPageStructure:
    def test_exactly_one_h1(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client)[0]:
            count = len(re.findall(r'<h1[\s>]', html))
            if count != 1:
                bad.append(f'{endpoint} ({url}): {count} <h1>')
        assert not bad, 'Сторінки не з одним <h1>:\n' + '\n'.join(bad)

    def test_canonical_absolute_and_clean(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client)[0]:
            found = re.search(r'<link rel="canonical" href="([^"]*)"', html)
            if not found:
                bad.append(f'{endpoint}: canonical відсутній')
                continue
            href = found.group(1)
            if not is_absolute_url(href):
                bad.append(f'{endpoint}: canonical не абсолютний -- {href}')
            if '?' in href:
                bad.append(f'{endpoint}: canonical із query -- {href}')
        assert not bad, 'Проблеми canonical:\n' + '\n'.join(bad)

    def test_meta_description_present(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client)[0]:
            if not head_field(html, 'description'):
                bad.append(f'{endpoint}: опис порожній або відсутній')
        assert not bad, 'Проблеми meta description:\n' + '\n'.join(bad)

    def test_jsonld_parses(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client)[0]:
            try:
                blocks = jsonld_blocks(html)
            except ValueError as exc:
                bad.append(f'{endpoint}: невалідний JSON-LD -- {exc}')
                continue
            for block in blocks:
                if '@context' not in block:
                    bad.append(f'{endpoint}: блок без @context')
                # @graph -- валідна альтернатива @type на верхньому рівні;
                # так побудована схема головної.
                elif '@type' not in block and '@graph' not in block:
                    bad.append(f'{endpoint}: блок без @type і без @graph')
        assert not bad, 'Проблеми JSON-LD:\n' + '\n'.join(bad)

    def test_every_public_page_has_at_least_one_jsonld_block(self, app, client):
        """Мовчання -- теж помилка.

        test_jsonld_parses не відрізняє "усе валідне" від "нічого не
        знайшлось": порожній список блоків проходить його бездоганно. Один
        зайвий атрибут у теґу <script> колись саме так і знеструмив усі
        твердження про структуровані дані одразу.
        """
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client)[0]:
            if not jsonld_blocks(html):
                bad.append(f'{endpoint} ({url})')
        assert not bad, (
            'Сторінки без жодного блоку JSON-LD:\n' + '\n'.join(bad)
        )


class TestTitleUniqueness:
    def _heads(self, app, client, field):
        values = {}
        for endpoint, url, html in fetch_public_pages(app, client)[0]:
            value = head_field(html, field)
            assert value, f'{endpoint}: <{field}> відсутній'
            values[endpoint] = value
        return values

    def test_titles_unique_except_known_debt(self, app, client):
        titles = self._heads(app, client, 'title')
        by_title = {}
        for endpoint, title in titles.items():
            by_title.setdefault(title, []).append(endpoint)

        # Дубль дозволений, лише поки хоча б один його ендпоінт значиться
        # у списку боргу.
        unexpected = {
            title: eps for title, eps in by_title.items()
            if len(eps) > 1 and not any(ep in KNOWN_SEO_DEBT for ep in eps)
        }
        assert not unexpected, f'Неврахований дубль title: {unexpected}'

    def test_descriptions_unique_except_known_debt(self, app, client):
        """Специфікація вимагала унікальності й описів, а не лише заголовків.

        Описи унікальні вже сьогодні -- тест не виправляє борг, а
        закріплює наявну властивість: два однакові description -- сигнал
        Google, що сторінки дублюють одна одну.
        """
        descriptions = self._heads(app, client, 'description')
        by_desc = {}
        for endpoint, desc in descriptions.items():
            by_desc.setdefault(desc, []).append(endpoint)

        unexpected = {
            desc[:60]: eps for desc, eps in by_desc.items()
            if len(eps) > 1 and not any(ep in KNOWN_SEO_DEBT for ep in eps)
        }
        assert not unexpected, f'Неврахований дубль description: {unexpected}'

    def test_known_debt_entries_are_still_real(self, app, client):
        """Виправив борг -- прибери запис. Інакше список бреше."""
        titles = self._heads(app, client, 'title')
        stale = []
        for endpoint in KNOWN_SEO_DEBT:
            if endpoint not in titles:
                continue
            twins = [
                other for other, title in titles.items()
                if title == titles[endpoint] and other != endpoint
            ]
            if not twins:
                stale.append(endpoint)
        assert not stale, f'KNOWN_SEO_DEBT застарів, прибери записи: {stale}'


def _measure_all_locales(app, client):
    """{(ендпоінт, локаль, поле): довжина} по всіх публічних сторінках.

    flask_babel.refresh() між локалями обов'язковий: db_session (conftest)
    тримає один app context на весь тест, і без refresh() flask_babel
    віддає закешовану на g._flask_babel локаль -- усі три прогони
    повернули б український рендер (та сама пастка описана в
    test_breadcrumbs.py).
    """
    measured = {}
    for lang in LANGUAGES:
        refresh()
        pages, _ = fetch_public_pages(app, client, lang=lang)
        for endpoint, _url, html in pages:
            for field in ('title', 'description'):
                value = head_field(html, field)
                if value is not None:
                    measured[(endpoint, lang, field)] = len(value)
    refresh()
    return measured


class TestLengths:
    def test_title_and_description_within_targets(self, app, client):
        """Межі перевіряються в УСІХ локалях, а не лише в українській.

        Доти, доки дивились тільки uk-рендер, ru/en виходили за межі
        непоміченими -- і сам цей план так завів два нові порушення."""
        limits = {'title': (TITLE_MIN, TITLE_MAX), 'description': (DESC_MIN, DESC_MAX)}
        bad = []
        for key, length in sorted(_measure_all_locales(app, client).items()):
            if key in LENGTH_EXCEPTIONS:
                continue
            endpoint, lang, field = key
            low, high = limits[field]
            if not low <= length <= high:
                bad.append(f'{endpoint} [{lang}]: {field} {length} симв.')
        report = '; '.join(bad)
        assert not bad, (
            f'Поза межами title {TITLE_MIN}-{TITLE_MAX}, '
            f'description {DESC_MIN}-{DESC_MAX}: {report}'
        )

    def test_length_exceptions_are_still_real(self, app, client):
        """Сторінка вийшла в межі -- прибери запис.

        KNOWN_SEO_DEBT мав такого сторожа з першого дня, LENGTH_EXCEPTIONS
        -- ні, і список міг тихо перетворитись на перелік уже неіснуючих
        проблем, який нічого не описує, зате прощає майбутні.
        """
        limits = {'title': (TITLE_MIN, TITLE_MAX), 'description': (DESC_MIN, DESC_MAX)}
        measured = _measure_all_locales(app, client)
        stale, unknown = [], []
        for key in LENGTH_EXCEPTIONS:
            endpoint, lang, field = key
            if key not in measured:
                unknown.append(key)
                continue
            low, high = limits[field]
            if low <= measured[key] <= high:
                stale.append(f'{endpoint} [{lang}] {field} = {measured[key]} симв.')
        assert not unknown, (
            f'LENGTH_EXCEPTIONS описує те, чого не існує: {unknown}'
        )
        assert not stale, (
            'LENGTH_EXCEPTIONS застарів, прибери записи: ' + '; '.join(stale)
        )

    def test_every_length_exception_has_a_reason(self):
        empty = [k for k, why in LENGTH_EXCEPTIONS.items() if not (why or '').strip()]
        assert not empty, f'Записи без причини: {empty}'
