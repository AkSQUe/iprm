"""Тести інтеграції курсів з медіа-реєстром (Фаза 5)."""
from tests.support.rbac import grant_role
import io
import tempfile
from uuid import uuid4

import pytest
from PIL import Image

from app.extensions import db
from app.models.user import User
from app.models.course import Course
from app.models.media_file import MediaFile


@pytest.fixture
def media_root(app):
    prev = app.config.get('MEDIA_FOLDER')
    app.config['MEDIA_FOLDER'] = tempfile.mkdtemp()
    yield app.config['MEDIA_FOLDER']
    app.config['MEDIA_FOLDER'] = prev


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'a-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _png():
    buf = io.BytesIO()
    Image.new('RGB', (900, 500), (120, 60, 30)).save(buf, 'PNG')
    buf.seek(0)
    return buf


class TestUploadAndProps:
    def test_course_upload_returns_media_id(self, client, admin, media_root):
        _login(client, admin)
        r = client.post('/admin/upload/course-image',
                        data={'file': (_png(), 'h.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 200
        j = r.get_json()
        assert j['media_id'] and j['url'].startswith('/media/') and j['card'].startswith('/media/')

    def test_src_props_media_only(self, client, admin, media_root):
        # Без media -> None; з media -> /media URL (Фаза 6: legacy-рядків немає).
        _login(client, admin)
        c = Course(title='T', slug=f't-{uuid4().hex[:6]}')
        db.session.add(c)
        db.session.flush()
        assert c.hero_src is None and c.card_src is None

        m = client.post('/admin/upload/course-image',
                        data={'file': (_png(), 'h.png')},
                        content_type='multipart/form-data').get_json()
        c.hero_media_id = m['media_id']
        c.card_media_id = m['media_id']
        db.session.flush()
        assert c.hero_src.startswith('/media/') and c.card_src.startswith('/media/')


class TestAttachOnSave:
    def test_create_attaches_hero_and_card(self, client, admin, media_root):
        _login(client, admin)
        hero = client.post('/admin/upload/course-image',
                           data={'file': (_png(), 'h.png')},
                           content_type='multipart/form-data').get_json()
        card = client.post('/admin/upload/course-image',
                           data={'file': (_png(), 'c.png')},
                           content_type='multipart/form-data').get_json()
        r = client.post('/admin/courses/new', data={
            'title': 'Курс із медіа', 'slug': f'k-{uuid4().hex[:6]}',
            'event_type': 'seminar', 'base_price': '0', 'is_active': 'y',
            'hero_media_id': str(hero['media_id']),
            'card_media_id': str(card['media_id']),
            'trainer_id': '0',
        }, follow_redirects=False)
        assert r.status_code in (302, 303), r.data[:300]

        c = Course.query.filter_by(title='Курс із медіа').first()
        assert c.hero_media_id == hero['media_id'] and c.card_media_id == card['media_id']
        hm = db.session.get(MediaFile, hero['media_id'])
        cm = db.session.get(MediaFile, card['media_id'])
        assert hm.entity_type == 'course' and hm.entity_id == c.id and hm.usage_type == 'hero'
        assert cm.entity_type == 'course' and cm.usage_type == 'card'
        assert hm.file_path.endswith('-hero.webp')
        assert cm.file_path.endswith('-card.webp')
