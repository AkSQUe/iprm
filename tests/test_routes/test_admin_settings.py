"""Тести сторінки /admin/settings."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.user import User


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'a-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_settings_page_has_hero_video_toggle(client, admin):
    _login(client, admin)
    r = client.get('/admin/settings')
    assert r.status_code == 200
    assert b'show_home_hero_video' in r.data
