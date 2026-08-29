"""Сторожі абсолютності URL у структурованих даних, набору hreflang і
закритості приватних розділів."""
import re

from app.i18n import LANGUAGES
from tests.test_seo.helpers import (
    fetch_public_pages, is_absolute_url, iter_url_values, jsonld_blocks,
)


class TestSchemaUrls:
    def test_schema_urls_absolute(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client)[0]:
            for block in jsonld_blocks(html):
                for key, value in iter_url_values(block):
                    if not is_absolute_url(value):
                        bad.append(f'{endpoint}: {key} = {value}')
        assert not bad, (
            'Відносні URL у структурованих даних:\n' + '\n'.join(bad)
        )


class TestHreflang:
    def test_localized_pages_list_all_languages(self, app, client):
        # Очікування виводимо з is_endpoint_expecting -- того самого
        # предиката, яким керується _hreflang_alternates() -- а не зі
        # списку локалізованих ендпоінтів, підтримуваного руками (він би
        # розходився з реальністю). Сторінка, що втратила alternates через
        # проковтнуте в i18n.py виключення, тепер падає, а не мовчки
        # пропускається порожнім набором.
        expected = set(LANGUAGES) | {'x-default'}
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client)[0]:
            langs = set(re.findall(
                r'<link rel="alternate" hreflang="([^"]+)"', html,
            ))
            localized = app.url_map.is_endpoint_expecting(
                endpoint, 'lang_code',
            )
            if localized:
                if langs != expected:
                    bad.append(
                        f'{endpoint}: очікували {sorted(expected)}, '
                        f'отримали {sorted(langs)}'
                    )
            elif langs:
                bad.append(
                    f'{endpoint}: hreflang не очікувався, отримали '
                    f'{sorted(langs)}'
                )
        assert not bad, (
            f'Невідповідність hreflang очікуваному {sorted(expected)}:\n'
            + '\n'.join(bad)
        )

    def test_hreflang_urls_absolute(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client)[0]:
            for href in re.findall(
                r'<link rel="alternate" hreflang="[^"]+" href="([^"]+)"', html,
            ):
                if not is_absolute_url(href):
                    bad.append(f'{endpoint}: {href}')
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
