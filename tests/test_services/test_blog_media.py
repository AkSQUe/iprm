"""Тести інтеграції блогу з медіа-реєстром (Фаза 3).

Покриває: санітайзер приймає /media + media_id + card, collect_media_ids,
прив'язку медіа до допису при збереженні.
"""
import io
import tempfile
from uuid import uuid4

import pytest
from PIL import Image

from app.extensions import db
from app.models.user import User
from app.models.blog_post import BlogPost
from app.models.media_file import MediaFile
from app.services import blog_service


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


def _png_file():
    buf = io.BytesIO()
    Image.new('RGB', (800, 600), (40, 90, 160)).save(buf, 'PNG')
    buf.seek(0)
    return buf


class TestSanitizer:
    def test_accepts_media_url_id_and_card(self):
        block = {'type': 'image', 'data': {
            'url': '/media/2026/06/abc123def456.webp',
            'thumb': '/media/2026/06/variants/thumb/abc_thumb.webp',
            'card': '/media/2026/06/variants/card/abc_card.webp',
            'media_id': 42, 'alt': 'опис', 'width': 800, 'height': 600,
        }}
        out = blog_service.sanitize_content([block])
        assert len(out) == 1
        d = out[0]['data']
        assert d['url'].startswith('/media/')
        assert d['card'].startswith('/media/')
        assert d['media_id'] == 42

    def test_still_accepts_legacy_static(self):
        block = {'type': 'image', 'data': {'url': '/static/images/blog/x.webp', 'alt': ''}}
        out = blog_service.sanitize_content([block])
        assert out and out[0]['data']['url'] == '/static/images/blog/x.webp'
        assert 'media_id' not in out[0]['data']

    def test_rejects_foreign_url_and_bad_media_id(self):
        block = {'type': 'image', 'data': {
            'url': 'https://evil.example/x.webp', 'media_id': 'abc',
        }}
        assert blog_service.sanitize_content([block]) == []

    def test_media_id_string_digits_coerced(self):
        block = {'type': 'image', 'data': {
            'url': '/media/2026/06/a.webp', 'media_id': '7',
        }}
        out = blog_service.sanitize_content([block])
        assert out[0]['data']['media_id'] == 7

    def test_collect_media_ids(self):
        blocks = [
            {'type': 'image', 'data': {'url': '/media/a.webp', 'media_id': 1}},
            {'type': 'gallery', 'data': {'images': [
                {'url': '/media/b.webp', 'media_id': 2},
                {'url': '/media/c.webp', 'media_id': 2},  # дубль
                {'url': '/static/images/blog/d.webp'},     # без id
            ]}},
            {'type': 'paragraph', 'data': {'html': 'текст'}},
        ]
        assert blog_service.collect_media_ids(blocks) == [1, 2]


class TestUploadToRegistry:
    def test_blog_upload_returns_media_id(self, client, admin, media_root):
        _login(client, admin)
        r = client.post('/admin/upload/blog-image',
                        data={'file': (_png_file(), 'p.png'), 'slug': 'post'},
                        content_type='multipart/form-data')
        assert r.status_code == 200
        j = r.get_json()
        assert j['media_id'] and j['url'].startswith('/media/')
        assert j['card'].startswith('/media/')
        m = db.session.get(MediaFile, j['media_id'])
        assert m.mime_type == 'image/webp' and m.entity_type is None


class TestAttachOnSave:
    def test_save_attaches_media_to_post(self, client, admin, media_root):
        _login(client, admin)
        # Завантажуємо обкладинку + контентне зображення у реєстр.
        cov = client.post('/admin/upload/blog-image',
                          data={'file': (_png_file(), 'c.png')},
                          content_type='multipart/form-data').get_json()
        img = client.post('/admin/upload/blog-image',
                          data={'file': (_png_file(), 'i.png')},
                          content_type='multipart/form-data').get_json()
        content = (
            '[{"type":"image","data":{"url":"%s","thumb":"%s","card":"%s",'
            '"media_id":%d,"alt":"x"}}]'
        ) % (img['url'], img['thumb'], img['card'], img['media_id'])
        r = client.post('/admin/blog/new', data={
            'title': 'Допис із медіа', 'status': 'draft',
            'cover_media_id': str(cov['media_id']),
            'content': content,
        }, follow_redirects=False)
        assert r.status_code in (302, 303)

        post = BlogPost.query.filter_by(title='Допис із медіа').first()
        assert post.cover_media_id == cov['media_id']
        cover_m = db.session.get(MediaFile, cov['media_id'])
        img_m = db.session.get(MediaFile, img['media_id'])
        assert cover_m.entity_type == 'blog_post' and cover_m.entity_id == post.id
        assert cover_m.usage_type == 'cover'
        assert img_m.entity_type == 'blog_post' and img_m.usage_type == 'inline'
        # читабельні імена файлів
        assert cover_m.file_path.endswith('-cover.webp')
        assert img_m.file_path.endswith('-inline-1.webp')
        # JSON-контент оновлено на нові URL
        blk = post.content[0]['data']
        assert blk['url'] == img_m.url and blk['url'].endswith('-inline-1.webp')
