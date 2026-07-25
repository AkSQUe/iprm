"""Тести кеш-політики HTML (app/__init__.py::cache_control_html).

Суть політики: `no-store` -- єдина директива, що вимикає bfcache у Chrome,
тож вона лишається тільки там, де у HTML можуть бути приватні дані. Публічні
сторінки для анонімів мають лишатись придатними для bfcache, інакше навігація
"назад" щоразу перезавантажує сторінку.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.user import User


@pytest.fixture
def user(app):
    u = User.create_with_password(
        f'u-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='U', last_name='T', email_confirmed=True,
    )
    db.session.flush()
    return u


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id)


def _cc(resp):
    return resp.headers.get('Cache-Control', '')


class TestPublicPages:
    @pytest.mark.parametrize('path', ['/', '/courses/', '/blog/', '/trainers/', '/contact'])
    def test_anonymous_html_is_bfcache_eligible(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 200
        assert 'no-store' not in _cc(resp), (
            f'{path}: no-store вимикає bfcache -- навігація "назад" '
            f'перезавантажує сторінку'
        )
        assert 'no-cache' in _cc(resp), f'{path}: сторінка має ревалідуватись'
        assert 'private' in _cc(resp)


class TestPrivatePages:
    @pytest.mark.parametrize('path', ['/auth/login', '/auth/register'])
    def test_auth_blueprint_stays_no_store(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 200
        assert 'no-store' in _cc(resp), f'{path}: приватний блупринт має лишатись no-store'

    def test_authenticated_public_page_is_no_store(self, client, user):
        _login(client, user)
        resp = client.get('/')
        assert resp.status_code == 200
        assert 'no-store' in _cc(resp), (
            'автентифікована відповідь може містити приватні дані -- '
            'у bfcache їй не місце'
        )


class TestNonHtml:
    def test_sitemap_keeps_its_own_policy(self, client):
        """Політика застосовується лише до text/html і не чіпає XML/JSON."""
        resp = client.get('/sitemap.xml')
        assert resp.status_code == 200
        assert 'public' in _cc(resp)
        assert 'max-age=3600' in _cc(resp)
