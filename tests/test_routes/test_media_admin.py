"""Тести адмін медіа-бібліотеки: рендер, завантаження, alt, видалення."""
import io
import tempfile
from uuid import uuid4

import pytest
from PIL import Image

from app.extensions import db
from app.models.user import User
from app.models.media_file import MediaFile


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'a-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


@pytest.fixture
def media_root(app):
    prev = app.config.get('MEDIA_FOLDER')
    app.config['MEDIA_FOLDER'] = tempfile.mkdtemp()
    yield
    app.config['MEDIA_FOLDER'] = prev


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _png():
    buf = io.BytesIO()
    Image.new('RGB', (800, 600), (90, 70, 160)).save(buf, 'PNG')
    buf.seek(0)
    return buf


class TestMediaAdmin:
    def test_library_renders(self, client, admin, media_root):
        _login(client, admin)
        assert client.get('/admin/media').status_code == 200

    def test_upload_creates_unattached(self, client, admin, media_root):
        _login(client, admin)
        r = client.post('/admin/upload/media',
                        data={'file': (_png(), 'a.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 200
        mid = r.get_json()['id']
        m = db.session.get(MediaFile, mid)
        assert m.entity_type is None and m.mime_type == 'image/webp'

    def test_alt_and_delete(self, client, admin, media_root):
        _login(client, admin)
        mid = client.post('/admin/upload/media',
                          data={'file': (_png(), 'a.png')},
                          content_type='multipart/form-data').get_json()['id']
        client.post(f'/admin/media/{mid}/alt', data={'alt': 'Опис'})
        assert db.session.get(MediaFile, mid).alt_text == 'Опис'
        client.post(f'/admin/media/{mid}/delete', data={})
        assert db.session.get(MediaFile, mid) is None

    def test_requires_admin(self, client, media_root):
        # без логіну -> редірект на логін (не 200)
        assert client.get('/admin/media').status_code in (301, 302)
