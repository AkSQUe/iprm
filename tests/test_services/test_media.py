"""Тести медіа-реєстру (MediaFile) та media_service: конверсія, варіанти,
запити, видалення, віддача /media."""
import io
import os
import tempfile

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.media_file import MediaFile
from app.services import media_service


@pytest.fixture
def media_root(app):
    """Тимчасова MEDIA_FOLDER на час тесту."""
    prev = app.config.get('MEDIA_FOLDER')
    app.config['MEDIA_FOLDER'] = tempfile.mkdtemp()
    yield app.config['MEDIA_FOLDER']
    app.config['MEDIA_FOLDER'] = prev


def _png(w=1200, h=900, color=(80, 60, 150)):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), color).save(buf, 'PNG')
    buf.seek(0)
    return FileStorage(stream=buf, filename='x.png', content_type='image/png')


class TestCreateFromUpload:
    def test_creates_webp_with_variants(self, media_root):
        media, err = media_service.create_from_upload(
            _png(2000, 1500), entity_type='trainer', entity_id=7,
            usage_type='certificate', alt_text='Серт',
        )
        db.session.flush()
        assert err is None
        assert media.mime_type == 'image/webp'
        assert media.width <= 1600
        assert set(media.responsive_variants.keys()) == {'thumb', 'card'}
        assert os.path.exists(media.abs_path)
        for rel in media.responsive_variants.values():
            assert os.path.exists(os.path.join(media_root, *rel.split('/')))

    def test_rejects_bad_extension(self, media_root):
        bad = FileStorage(stream=io.BytesIO(b'x'), filename='evil.exe')
        media, err = media_service.create_from_upload(bad)
        assert media is None and err

    def test_rejects_garbage_image(self, media_root):
        bad = FileStorage(stream=io.BytesIO(b'notanimage'), filename='x.png')
        media, err = media_service.create_from_upload(bad)
        assert media is None and err


class TestQueriesAndUrls:
    def test_for_entity_ordering_and_main(self, media_root):
        a, _ = media_service.create_from_upload(_png(), entity_type='trainer', entity_id=1, usage_type='certificate', sort_order=2)
        b, _ = media_service.create_from_upload(_png(), entity_type='trainer', entity_id=1, usage_type='certificate', sort_order=1)
        db.session.flush()
        items = MediaFile.for_entity('trainer', 1, 'certificate').all()
        assert [m.id for m in items] == [b.id, a.id]  # за sort_order
        main = MediaFile.main_for('trainer', 1, 'certificate')
        assert main.id == b.id

    def test_urls(self, media_root):
        m, _ = media_service.create_from_upload(_png())
        db.session.flush()
        assert m.url.startswith('/media/')
        assert m.variant_url('thumb').endswith('.webp')
        assert m.variant_url('nonexistent') == m.url  # fallback


class TestRenameForEntity:
    def test_rename_main_and_variants(self, media_root):
        m, _ = media_service.create_from_upload(_png(), usage_type='photo')
        db.session.flush()
        old_url = m.url
        mapping = media_service.rename_for_entity(m, 'ivan-petrenko')
        db.session.flush()
        # ім'я стало читабельним, фізичні файли на місці
        assert m.file_path.endswith('ivan-petrenko-photo.webp')
        assert os.path.exists(m.abs_path)
        for rel in m.responsive_variants.values():
            assert 'ivan-petrenko-photo' in rel
            assert os.path.exists(os.path.join(media_root, *rel.split('/')))
        # mapping містить старий->новий для основного + варіантів
        assert mapping[old_url] == m.url
        # ідемпотентність: повторний виклик нічого не змінює
        assert media_service.rename_for_entity(m, 'ivan-petrenko') == {}

    def test_rename_with_index(self, media_root):
        m, _ = media_service.create_from_upload(_png(), usage_type='certificate')
        db.session.flush()
        media_service.rename_for_entity(m, 'ivan-petrenko', 3)
        assert m.file_path.endswith('ivan-petrenko-certificate-3.webp')


class TestDeleteAndServe:
    def test_delete_removes_files(self, media_root):
        m, _ = media_service.create_from_upload(_png())
        db.session.flush()
        paths = [m.abs_path] + [os.path.join(media_root, *r.split('/')) for r in m.responsive_variants.values()]
        media_service.delete_media(m)
        db.session.flush()
        assert all(not os.path.exists(p) for p in paths)

    def test_serve_route(self, client, media_root):
        m, _ = media_service.create_from_upload(_png())
        db.session.flush()
        assert client.get(m.url).status_code == 200
        assert client.get('/media/2026/06/nope.webp').status_code == 404
