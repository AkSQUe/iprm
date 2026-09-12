"""Тести адмін медіа-бібліотеки: рендер, завантаження, alt, видалення."""
from tests.support.rbac import grant_role, switch_user
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
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
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
        # М'яке видалення: рядок лишається (щоб був відкат), але зникає зі
        # списків і з віддачі контенту.
        assert db.session.get(MediaFile, mid).is_deleted
        assert MediaFile.alive().filter_by(id=mid).first() is None

    def test_requires_admin(self, client, media_root):
        # без логіну -> редірект на логін (не 200)
        assert client.get('/admin/media').status_code in (301, 302)

    def test_list_json(self, client, admin, media_root):
        _login(client, admin)
        client.post('/admin/upload/media', data={'file': (_png(), 'a.png')},
                    content_type='multipart/form-data')
        r = client.get('/admin/media/list.json')
        assert r.status_code == 200
        j = r.get_json()
        assert 'items' in j and len(j['items']) >= 1
        assert j['items'][0]['url'].startswith('/media/')

    def test_bulk_delete(self, client, admin, media_root):
        _login(client, admin)
        id1 = client.post('/admin/upload/media', data={'file': (_png(), 'a.png')},
                          content_type='multipart/form-data').get_json()['id']
        id2 = client.post('/admin/upload/media', data={'file': (_png(), 'b.png')},
                          content_type='multipart/form-data').get_json()['id']
        client.post('/admin/media/bulk-delete', data={'ids': [str(id1), str(id2)]})
        assert db.session.get(MediaFile, id1).is_deleted
        assert db.session.get(MediaFile, id2).is_deleted
        # Відкат повертає обидва (файли непривʼязані -- відкат повний).
        client.post(f'/admin/media/restore?ids={id1},{id2}')
        assert not db.session.get(MediaFile, id1).is_deleted
        assert not db.session.get(MediaFile, id2).is_deleted

    def test_delete_attached_detaches_blog_content(self, client, admin, media_root):
        # Видалення медіа, що використовується в inline-блоці допису, прибирає
        # блок із контенту (без «битого» URL).
        from app.models.blog_post import BlogPost
        _login(client, admin)
        mid = client.post('/admin/upload/media',
                          data={'file': (_png(), 'a.png')},
                          content_type='multipart/form-data').get_json()['id']
        media = db.session.get(MediaFile, mid)
        media.entity_type = 'blog_post'
        post = BlogPost(slug=f'p-{uuid4().hex[:6]}', title='T', status='draft',
                        content=[{'type': 'image', 'data': {'url': media.url, 'media_id': mid}},
                                 {'type': 'paragraph', 'data': {'html': 'текст'}}])
        db.session.add(post)
        db.session.flush()
        media.entity_id = post.id
        db.session.commit()

        client.post(f'/admin/media/{mid}/delete', data={})
        assert db.session.get(MediaFile, mid).is_deleted
        refreshed = db.session.get(BlogPost, post.id)
        types = [b['type'] for b in refreshed.content]
        assert 'image' not in types and 'paragraph' in types

    def test_attached_delete_offers_no_undo(self, client, admin, media_root):
        """Відкат не повернув би блок у контенті -- отже його не пропонуємо."""
        from app.models.blog_post import BlogPost
        _login(client, admin)
        mid = client.post('/admin/upload/media',
                          data={'file': (_png(), 'a.png')},
                          content_type='multipart/form-data').get_json()['id']
        media = db.session.get(MediaFile, mid)
        post = BlogPost(slug=f'p-{uuid4().hex[:6]}', title='T', status='draft',
                        content=[{'type': 'image', 'data': {'url': media.url, 'media_id': mid}}])
        db.session.add(post)
        db.session.flush()
        media.entity_type, media.entity_id = 'blog_post', post.id
        db.session.commit()

        client.post(f'/admin/media/{mid}/delete', data={})
        with client.session_transaction() as s:
            assert 'undo_offer' not in s


def _viewer_with(*perms):
    """Роль рівно з переліченими правами -- щоб перевірити, що сторінка не
    показує кнопок, які ця роль не має права натиснути."""
    from app.models.rbac import Permission, Role
    from tests.support.rbac import make_user_with_role
    role = Role(name='t_media_' + '_'.join(p.replace('.', '') for p in perms),
                display_name='T')
    for name in perms:
        role.permissions.append(Permission.query.filter_by(name=name).one())
    db.session.add(role)
    db.session.flush()
    return make_user_with_role(role.name)


def _upload(client, name='a.png'):
    return client.post('/admin/upload/media',
                       data={'file': (_png(), name)},
                       content_type='multipart/form-data').get_json()['id']


class TestMediaTrash:
    """Кошик: вікно відкату існує в БД 30 днів, і до нього мусять бути двері.

    Доти єдиним шляхом до `media_restore` був тост «Повернути»: закрив
    вкладку -- і місяць даних недосяжний.
    """

    def test_deleted_file_is_visible_in_trash_only(self, client, admin, media_root):
        _login(client, admin)
        mid = _upload(client)
        client.post(f'/admin/media/{mid}/delete', data={})

        alive = client.get('/admin/media').get_data(as_text=True)
        assert f'id="media-{mid}"' not in alive

        trash = client.get('/admin/media?state=trash').get_data(as_text=True)
        assert f'id="media-{mid}"' in trash
        assert 'Зникне назавжди' in trash

    def test_restore_from_trash_form(self, client, admin, media_root):
        """Кошик шле ids полем форми, тост -- через кому в query-string.
        Обидва джерела мусять працювати: посилання тоста живе у вже відданій
        користувачу сторінці, переписати його не можна."""
        _login(client, admin)
        mid = _upload(client)
        client.post(f'/admin/media/{mid}/delete', data={})
        client.post('/admin/media/restore', data={'ids': [str(mid)]})
        assert not db.session.get(MediaFile, mid).is_deleted

    def test_empty_trash_says_so(self, client, admin, media_root):
        """Кошик -- поточний вид, а не звуження: порожній він каже «Кошик
        порожній», а не «Нічого не знайдено»."""
        _login(client, admin)
        html = client.get('/admin/media?state=trash').get_data(as_text=True)
        assert 'Кошик порожній' in html

    def test_purge_at_is_retention_days_after_delete(self, client, admin, media_root):
        from app.services.soft_delete_purge import RETENTION_DAYS
        from app.utils import ensure_utc
        _login(client, admin)
        mid = _upload(client)
        client.post(f'/admin/media/{mid}/delete', data={})
        media = db.session.get(MediaFile, mid)
        assert (media.purge_at - ensure_utc(media.deleted_at)).days == RETENTION_DAYS


class TestMediaListing:
    def test_online_course_binding_is_filterable_and_named(self, client, admin, media_root):
        """`online_course` реально пишеться в реєстр, але фільтр про нього не
        знав, а картка друкувала сирий код."""
        _login(client, admin)
        mid = _upload(client)
        media = db.session.get(MediaFile, mid)
        media.entity_type, media.entity_id = 'online_course', 7
        db.session.commit()

        html = client.get('/admin/media?entity_type=online_course').get_data(as_text=True)
        assert f'id="media-{mid}"' in html
        assert 'Онлайн-курс #7' in html

    def test_usage_type_shown_by_human_label(self, client, admin, media_root):
        _login(client, admin)
        mid = _upload(client)
        media = db.session.get(MediaFile, mid)
        media.entity_type, media.entity_id, media.usage_type = 'course', 3, 'hero'
        db.session.commit()
        html = client.get('/admin/media').get_data(as_text=True)
        assert 'Банер' in html

    def test_sort_by_size_puts_heaviest_first(self, client, admin, media_root):
        _login(client, admin)
        light, heavy = _upload(client, 'light.png'), _upload(client, 'heavy.png')
        db.session.get(MediaFile, light).file_size = 1_000
        db.session.get(MediaFile, heavy).file_size = 900_000
        db.session.commit()
        html = client.get('/admin/media?sort=size').get_data(as_text=True)
        assert html.index(f'id="media-{heavy}"') < html.index(f'id="media-{light}"')

    def test_unknown_filter_value_falls_back_to_full_list(self, client, admin, media_root):
        """`choice_arg`: сміття в URL зі старого посилання дає повний список,
        а не порожній екран."""
        _login(client, admin)
        mid = _upload(client)
        html = client.get('/admin/media?usage_type=zzz&entity_type=zzz').get_data(as_text=True)
        assert f'id="media-{mid}"' in html

    def test_empty_search_offers_reset(self, client, admin, media_root):
        _login(client, admin)
        _upload(client)
        html = client.get('/admin/media?q=nosuchthing').get_data(as_text=True)
        assert 'Нічого не знайдено' in html and 'скинути фільтри' in html

    def test_picker_json_searches(self, client, admin, media_root):
        _login(client, admin)
        wanted = _upload(client, 'plazma-hero.png')
        _upload(client, 'other.png')
        items = client.get('/admin/media/list.json?q=plazma').get_json()['items']
        assert [i['id'] for i in items] == [wanted]


class TestMediaPermissions:
    def test_view_only_role_sees_no_actions(self, client, admin, media_root):
        """Кнопка, яку ця роль не має права натиснути, веде рівно в 403 --
        показувати її означає обіцяти дію, якої немає."""
        _login(client, admin)
        _upload(client)
        switch_user(client, _viewer_with('media.view'))
        html = client.get('/admin/media').get_data(as_text=True)
        assert 'media-upload' not in html
        assert 'media-card__alt' not in html
        assert 'Видалити вибране' not in html
        assert 'media-bulk-form' not in html

    def test_view_only_role_is_refused_by_the_route_too(self, client, admin, media_root):
        _login(client, admin)
        mid = _upload(client)
        switch_user(client, _viewer_with('media.view'))
        assert client.post(f'/admin/media/{mid}/delete', data={}).status_code == 403
        assert not db.session.get(MediaFile, mid).is_deleted


class TestMediaBulkGuards:
    def test_bulk_ids_are_capped(self, app):
        """Стеля на кількість id -- той самий клас запобіжника, що MAX_PAGE
        для номера сторінки: без неї POST зі 100k значень дає IN-клаузу на
        100k параметрів."""
        from app.admin.routes_media import _MAX_BULK_IDS, _ids_arg
        assert len(_ids_arg([str(i) for i in range(1, _MAX_BULK_IDS + 50)])) == _MAX_BULK_IDS
        assert _ids_arg(['12', 'abc', '', ' 7 ']) == [12, 7]

    def test_bulk_delete_keeps_the_slice(self, client, admin, media_root):
        """Дія повертає на той самий зріз: інакше кожне видалення на другій
        сторінці викидало б адміна на першу сторінку без фільтра."""
        _login(client, admin)
        mid = _upload(client)
        r = client.post('/admin/media/bulk-delete?entity_type=none',
                        data={'ids': [str(mid)]})
        assert r.status_code in (301, 302)
        assert 'entity_type=none' in r.headers['Location']
