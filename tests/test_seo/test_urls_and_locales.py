"""Сторожі абсолютності URL у структурованих даних, набору hreflang і
закритості приватних розділів."""
import re

from app.i18n import LANGUAGES
from tests.test_seo.helpers import (
    LOCALE_PASSES, fetch_public_pages, is_absolute_url, iter_url_values,
    jsonld_blocks, pass_label,
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
