"""Тести інтеграції тренерів з медіа-реєстром (Фаза 4)."""
import io
import tempfile
from uuid import uuid4

import pytest
from PIL import Image

from app.extensions import db
from app.models.user import User
from app.models.trainer import Trainer
from app.models.media_file import MediaFile
from app.services import trainer_service


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
    Image.new('RGB', (700, 500), (60, 120, 90)).save(buf, 'PNG')
    buf.seek(0)
    return buf


class TestSanitizer:
    def test_cert_accepts_media_id_and_card(self):
        items = [{'url': '/media/2026/06/a.webp', 'thumb': '/media/2026/06/t.webp',
                  'card': '/media/2026/06/c.webp', 'media_id': 5, 'caption': 'C'}]
        out = trainer_service.sanitize_certificates(items)
        assert out[0]['media_id'] == 5 and out[0]['card'].startswith('/media/')

    def test_cert_legacy_static_no_media_id(self):
        items = [{'url': '/static/images/trainers/x/y.webp'}]
        out = trainer_service.sanitize_certificates(items)
        assert out and 'media_id' not in out[0]

    def test_patent_media_id_requires_image(self):
        # media_id без зображення відкидається (патент може бути лише посиланням)
        items = [{'url': 'https://patents.example/1', 'media_id': 9, 'label': 'P'}]
        out = trainer_service.sanitize_patents(items)
        assert out and 'media_id' not in out[0]

    def test_patent_with_media_image(self):
        items = [{'image': '/media/2026/06/p.webp', 'card': '/media/2026/06/pc.webp',
                  'media_id': '11', 'label': 'Патент'}]
        out = trainer_service.sanitize_patents(items)
        assert out[0]['media_id'] == 11 and out[0]['card'].startswith('/media/')

    def test_collect_media_ids(self):
        t = Trainer(full_name='T', slug='t')
        t.photo_media_id = 1
        t.certificates = [{'url': '/media/a.webp', 'media_id': 2}]
        t.patents = [{'image': '/media/b.webp', 'media_id': 3}, {'url': 'https://x/y'}]
        ids = trainer_service.collect_media_ids(t)
        assert ids == {1: 'photo', 2: 'certificate', 3: 'patent'}


class TestUploads:
    def test_photo_upload_returns_media_id(self, client, admin, media_root):
        _login(client, admin)
        r = client.post('/admin/upload/trainer-image',
                        data={'file': (_png(), 'p.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 200 and r.get_json()['media_id']
        assert r.get_json()['url'].startswith('/media/')

    def test_certificate_upload_returns_media_id(self, client, admin, media_root):
        _login(client, admin)
        r = client.post('/admin/upload/trainer-certificate',
                        data={'file': (_png(), 'c.png')},
                        content_type='multipart/form-data')
        assert r.status_code == 200 and r.get_json()['media_id']


class TestAttachOnSave:
    def test_create_attaches_photo_and_cert(self, client, admin, media_root):
        _login(client, admin)
        photo = client.post('/admin/upload/trainer-image',
                            data={'file': (_png(), 'p.png')},
                            content_type='multipart/form-data').get_json()
        cert = client.post('/admin/upload/trainer-certificate',
                           data={'file': (_png(), 'c.png')},
                           content_type='multipart/form-data').get_json()
        certs_json = (
            '[{"url":"%s","thumb":"%s","card":"%s","media_id":%d,"caption":"C"}]'
        ) % (cert['url'], cert['thumb'], cert['card'], cert['media_id'])
        r = client.post('/admin/trainers/new', data={
            'full_name': 'Тест Тренер', 'slug': f't-{uuid4().hex[:6]}',
            'is_active': 'y',
            'photo_media_id': str(photo['media_id']),
            'certificates': certs_json, 'patents': '[]', 'articles': '[]',
            'research': '', 'skills': '', 'education': '',
            'additional_education': '', 'work_experience': '',
        }, follow_redirects=False)
        assert r.status_code in (302, 303)

        t = Trainer.query.filter_by(full_name='Тест Тренер').first()
        assert t.photo_media_id == photo['media_id']
        pm = db.session.get(MediaFile, photo['media_id'])
        cm = db.session.get(MediaFile, cert['media_id'])
        assert pm.entity_type == 'trainer' and pm.entity_id == t.id and pm.usage_type == 'photo'
        assert cm.entity_type == 'trainer' and cm.usage_type == 'certificate'
        # читабельні імена + оновлений JSON
        assert pm.file_path.endswith('-photo.webp')
        assert cm.file_path.endswith('-certificate-1.webp')
        assert t.certificates[0]['url'] == cm.url
