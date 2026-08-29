"""Сторожі публічних сторінок: заголовок, canonical, опис, валідність
структурованих даних."""
import re

from tests.test_seo.helpers import (
    DESC_MAX, DESC_MIN, KNOWN_SEO_DEBT, LENGTH_EXCEPTIONS,
    TITLE_MAX, TITLE_MIN, fetch_public_pages, jsonld_blocks,
)


class TestPageStructure:
    def test_exactly_one_h1(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            count = len(re.findall(r'<h1[\s>]', html))
            if count != 1:
                bad.append(f'{endpoint} ({url}): {count} <h1>')
        assert not bad, 'Сторінки не з одним <h1>:\n' + '\n'.join(bad)

    def test_canonical_absolute_and_clean(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            found = re.search(r'<link rel="canonical" href="([^"]*)"', html)
            if not found:
                bad.append(f'{endpoint}: canonical відсутній')
                continue
            href = found.group(1)
            if not href.startswith('http'):
                bad.append(f'{endpoint}: canonical не абсолютний -- {href}')
            if '?' in href:
                bad.append(f'{endpoint}: canonical із query -- {href}')
        assert not bad, 'Проблеми canonical:\n' + '\n'.join(bad)

    def test_meta_description_present(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            found = re.search(
                r'<meta name="description" content="([^"]*)"', html,
            )
            if not found or not found.group(1).strip():
                bad.append(f'{endpoint}: опис порожній або відсутній')
        assert not bad, 'Проблеми meta description:\n' + '\n'.join(bad)

    def test_jsonld_parses(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
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


class TestTitleUniqueness:
    def _titles(self, app, client):
        titles = {}
        for endpoint, url, html in fetch_public_pages(app, client):
            found = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
            assert found, f'{endpoint}: <title> відсутній'
            titles[endpoint] = found.group(1).strip()
        return titles

    def test_titles_unique_except_known_debt(self, app, client):
        titles = self._titles(app, client)
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

    def test_known_debt_entries_are_still_real(self, app, client):
        """Виправив борг -- прибери запис. Інакше список бреше."""
        titles = self._titles(app, client)
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


class TestLengths:
    def test_title_and_description_within_targets(self, app, client):
        bad = []
        for endpoint, url, html in fetch_public_pages(app, client):
            if endpoint in LENGTH_EXCEPTIONS:
                continue
            title = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
            desc = re.search(
                r'<meta name="description" content="([^"]*)"', html,
            )
            if title:
                length = len(title.group(1).strip())
                if not TITLE_MIN <= length <= TITLE_MAX:
                    bad.append(f'{endpoint}: title {length} симв.')
            if desc:
                length = len(desc.group(1).strip())
                if not DESC_MIN <= length <= DESC_MAX:
                    bad.append(f'{endpoint}: description {length} симв.')
        report = '; '.join(bad)
        assert not bad, (
            f'Поза межами title {TITLE_MIN}-{TITLE_MAX}, '
            f'description {DESC_MIN}-{DESC_MAX}: {report}'
        )
