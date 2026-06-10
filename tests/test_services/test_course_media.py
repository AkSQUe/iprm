"""Тести інтеграції курсів з медіа-реєстром (Фаза 5)."""
import io
import os
import tempfile
from uuid import uuid4

import pytest
from PIL import Image

from app.extensions import db
from app.models.user import User
from app.models.course import Course
from app.models.media_file import MediaFile
from app.services import course_service


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
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
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

    def test_src_props_prefer_media(self, media_root):
        c = Course(title='T', slug=f't-{uuid4().hex[:6]}',
                   hero_image='/static/images/courses/x/h.webp',
                   card_image='/static/images/courses/x/c.webp')
        db.session.add(c)
        db.session.flush()
        # без media -> legacy
        assert c.hero_src.endswith('h.webp') and c.card_src.endswith('c.webp')


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
            'hero_image': hero['url'], 'hero_media_id': str(hero['media_id']),
            'card_image': card['url'], 'card_media_id': str(card['media_id']),
            'trainer_id': '0',
        }, follow_redirects=False)
        assert r.status_code in (302, 303), r.data[:300]

        c = Course.query.filter_by(title='Курс із медіа').first()
        assert c.hero_media_id == hero['media_id'] and c.card_media_id == card['media_id']
        hm = db.session.get(MediaFile, hero['media_id'])
        cm = db.session.get(MediaFile, card['media_id'])
        assert hm.entity_type == 'course' and hm.entity_id == c.id and hm.usage_type == 'hero'
        assert cm.entity_type == 'course' and cm.usage_type == 'card'


class TestMigrationCLI:
    def test_migrate_hero_and_card(self, app, media_root):
        runner = app.test_cli_runner()
        cdir = os.path.join(app.static_folder, 'images', 'courses', 'mig')
        os.makedirs(cdir, exist_ok=True)
        hf, cf = f'{uuid4().hex[:8]}.webp', f'{uuid4().hex[:8]}.webp'
        Image.new('RGB', (1200, 600), (1, 1, 1)).save(os.path.join(cdir, hf), 'WEBP')
        Image.new('RGB', (400, 200), (2, 2, 2)).save(os.path.join(cdir, cf), 'WEBP')
        c = Course(title='Старий курс', slug=f's-{uuid4().hex[:6]}',
                   hero_image=f'/static/images/courses/mig/{hf}',
                   card_image=f'/static/images/courses/mig/{cf}')
        db.session.add(c)
        db.session.commit()
        cid = c.id

        res = runner.invoke(args=['course-media-migrate'])
        assert res.exit_code == 0, res.output

        m = db.session.get(Course, cid)
        assert m.hero_media_id and m.hero_image.startswith('/media/')
        assert m.card_media_id and m.card_image.startswith('/media/')

        # ідемпотентність
        prev_hero = m.hero_media_id
        res2 = runner.invoke(args=['course-media-migrate'])
        assert res2.exit_code == 0
        assert db.session.get(Course, cid).hero_media_id == prev_hero
        os.remove(os.path.join(cdir, hf))
        os.remove(os.path.join(cdir, cf))
