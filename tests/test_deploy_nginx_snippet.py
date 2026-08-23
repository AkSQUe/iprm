"""Вартовий над deploy/nginx/snippets/iprm-app.conf.

Файл не виконується в тестах і не покривається нічим іншим, але кожна з
перевірених тут властивостей уже коштувала проду:

  * буквальний хост у proxy_pass змушує nginx резолвити DNS НА СТАРТІ й
    відмовлятись підніматись при збої DNS -- так сайт ліг 29.07.2026;
  * без заголовка Host PostHog віддає 401 на кожен запит;
  * без окремої локації /array/ SDK не отримує ремоут-конфіг: події йдуть,
    а реплею немає, і помітно це не одразу;
  * глобальні 25m ріжуть батчі записів сесій з 413.

Тест читає конфіг як текст. Це груба перевірка, але вона ловить саме те, що
губиться при ручній правці сніпета.
"""
import re
from pathlib import Path

import pytest

SNIPPET = Path(__file__).resolve().parents[1] / 'deploy' / 'nginx' / 'snippets' / 'iprm-app.conf'


@pytest.fixture(scope='module')
def conf():
    return SNIPPET.read_text(encoding='utf-8')


def _location_body(conf, header):
    """Тіло location-блоку за його заголовком (до першої закривної дужки)."""
    start = conf.index(header)
    body = conf[start + len(header):]
    return body[:body.index('\n}')]


class TestDnsOutageGuard:
    def test_no_literal_host_in_proxy_pass(self, conf):
        """Усі зовнішні апстріми -- через змінні.

        Виняток -- лише unix-сокет застосунку: він не резолвиться через DNS.
        """
        offenders = [
            line.strip() for line in conf.splitlines()
            # Коментарі пропускаємо: попередження про саму цю пастку
            # написане словами і містить слово proxy_pass.
            if not line.lstrip().startswith('#')
            and 'proxy_pass' in line
            and 'http://unix:' not in line
            and '$' not in line
        ]
        assert not offenders, (
            f'буквальний хост у proxy_pass кладе nginx при збої DNS: {offenders}'
        )

    def test_resolver_declared(self, conf):
        assert re.search(r'^\s*resolver\s+\S', conf, re.M), (
            'без resolver змінна в proxy_pass не резолвиться взагалі'
        )


class TestPosthogProxy:
    @pytest.mark.parametrize('header', [
        'location /ngx-e/static/ {',
        'location /ngx-e/array/ {',
        'location /ngx-e/ {',
    ])
    def test_all_three_locations_present(self, conf, header):
        """PostHog розводить трафік на два апстріми, тож локацій саме три."""
        assert header in conf

    def test_assets_and_api_go_to_different_upstreams(self, conf):
        static_body = _location_body(conf, 'location /ngx-e/static/ {')
        array_body = _location_body(conf, 'location /ngx-e/array/ {')
        api_body = _location_body(conf, 'location /ngx-e/ {')
        assert 'eu-assets.i.posthog.com' in static_body
        assert 'eu-assets.i.posthog.com' in array_body
        assert 'eu-assets' not in api_body
        assert 'eu.i.posthog.com' in api_body

    @pytest.mark.parametrize('header', [
        'location /ngx-e/static/ {',
        'location /ngx-e/array/ {',
        'location /ngx-e/ {',
    ])
    def test_host_header_set(self, conf, header):
        """Без Host PostHog віддає 401 на кожен запит."""
        assert 'proxy_set_header Host ' in _location_body(conf, header)

    def test_session_recording_body_size_raised(self, conf):
        """Батчі записів сесій більші за глобальні 25m."""
        assert 'client_max_body_size 64m' in _location_body(conf, 'location /ngx-e/ {')

    def test_client_ip_forwarded(self, conf):
        """PostHog визначає гео за X-Forwarded-For."""
        assert 'X-Forwarded-For' in _location_body(conf, 'location /ngx-e/ {')

    def test_remote_config_not_cached(self, conf):
        """Закешований 301 з ротованого IP апстріму ламає config.js назавжди
        для браузера (відкритий баг PostHog)."""
        assert 'no-store' in _location_body(conf, 'location /ngx-e/array/ {')


class TestGoogleAnalyticsProxy:
    def test_locations_still_present(self, conf):
        """GA-проксі не має постраждати від сусідства з PostHog."""
        assert 'location = /ngx-i/loader.js {' in conf
        assert 'location /ngx-i/g/ {' in conf
