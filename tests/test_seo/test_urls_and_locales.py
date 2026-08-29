"""Сторожі абсолютності URL у структурованих даних, набору hreflang і
закритості приватних розділів."""
import re

from app.i18n import LANGUAGES
from tests.test_seo.helpers import (
    fetch_public_pages, iter_url_values, jsonld_blocks,
)


class TestSchemaUrls:
    def test_schema_urls_absolute(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            for block in jsonld_blocks(html):
                for key, value in iter_url_values(block):
                    if not value.startswith('http'):
                        bad.append(f'{endpoint}: {key} = {value}')
        assert not bad, (
            'Відносні URL у структурованих даних:\n' + '\n'.join(bad)
        )


class TestHreflang:
    def test_localized_pages_list_all_languages(self, app, client):
        expected = set(LANGUAGES) | {'x-default'}
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            langs = set(re.findall(
                r'<link rel="alternate" hreflang="([^"]+)"', html,
            ))
            if not langs:
                # Нелокалізований ендпоінт (юридичні сторінки) -- штатно.
                continue
            if langs != expected:
                bad.append(f'{endpoint}: {sorted(langs)}')
        assert not bad, (
            f'Набір hreflang не дорівнює {sorted(expected)}:\n'
            + '\n'.join(bad)
        )

    def test_hreflang_urls_absolute(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            for href in re.findall(
                r'<link rel="alternate" hreflang="[^"]+" href="([^"]+)"', html,
            ):
                if not href.startswith('http'):
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
