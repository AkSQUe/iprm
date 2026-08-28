"""Каталог живе в адмінці, під логіном, і має вихід зі старої адреси."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.user import User


@pytest.fixture
def admin():
    # Email унікальний: тести ділять сесію додатка, і фіксована адреса
    # зіткнулась би з unique-індексом users.email у сусідньому тесті.
    u = User.create_with_password(
        f'ds-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_catalog_requires_admin(client):
    resp = client.get('/admin/design-system')
    assert resp.status_code in (302, 401, 403)


def test_catalog_renders_for_admin(client, admin):
    _login(client, admin)
    resp = client.get('/admin/design-system')
    assert resp.status_code == 200
    assert 'ds-section' in resp.get_data(as_text=True)


def test_old_public_url_redirects(client):
    resp = client.get('/design-system')
    assert resp.status_code in (301, 302)
    assert '/admin/design-system' in resp.headers['Location']
