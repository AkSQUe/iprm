"""Адмін-редактор перекладів: доступ, round-trip рядків і JSON,
фільтр шляхів-ассетів, префіл, покриття."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.i18n import source_key, walk_leaves
from app.models.blog_post import BlogPost
from app.models.course import Course
from app.models.user import User


@pytest.fixture
def admin():
    u = User.create_with_password(
        f'a-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _course():
    c = Course(title='Курс', slug=f'c-{uuid4().hex[:6]}', is_active=True)
    db.session.add(c)
    db.session.flush()
    return c


def test_editor_requires_admin(client):
    c = _course()
    r = client.get(f'/admin/translations/course/{c.id}')
    assert r.status_code in (302, 401, 403)


def test_editor_get_renders_fields(client, admin):
    _login(client, admin)
    c = _course()
    html = client.get(f'/admin/translations/course/{c.id}').get_data(as_text=True)
    assert 'ru__title' in html and 'en__title' in html


def test_editor_unknown_entity_404(client, admin):
    _login(client, admin)
    assert client.get('/admin/translations/nope/1').status_code == 404


def test_editor_saves_text_translation(client, admin):
    _login(client, admin)
    c = _course()
    r = client.post(f'/admin/translations/course/{c.id}',
                    data={'ru__title': 'Курс-РУ', 'en__title': 'Course-EN'})
    assert r.status_code == 302
    fetched = db.session.get(Course, c.id)
    assert fetched.translations['ru']['title'] == 'Курс-РУ'
    assert fetched.translations['en']['title'] == 'Course-EN'


def test_walk_leaves_excludes_asset_paths():
    content = [
        {'type': 'paragraph', 'data': {'html': 'Абзац тексту.'}},
        {'type': 'image', 'data': {'thumb': '/media/x_thumb.webp', 'caption': 'Підпис'}},
        'photo_gallery.webp',
    ]
    values = [v for _, v in walk_leaves(content)]
    assert 'Абзац тексту.' in values
    assert 'Підпис' in values
    assert not any('webp' in v or v.startswith('/media') for v in values)


def test_editor_saves_json_as_override_map(client, admin):
    _login(client, admin)
    p = BlogPost(slug=f'p-{uuid4().hex[:6]}', title='T', status='published',
                 content=[{'type': 'paragraph', 'data': {'html': 'Оригінал.'}}])
    db.session.add(p)
    db.session.flush()
    key = source_key('Оригінал.')
    r = client.post(f'/admin/translations/blog_post/{p.id}',
                    data={f'ru__content__{key}': 'Оригинал.'})
    assert r.status_code == 302
    fetched = db.session.get(BlogPost, p.id)
    stored = fetched.translations['ru']['content']
    assert isinstance(stored, dict)  # override-мапа, не повна структура
    # Ключ -- хеш українського джерела, а не позиція в структурі.
    assert stored == {key: 'Оригинал.'}
    assert fetched.t('content', lang='ru')[0]['data']['html'] == 'Оригинал.'


def test_editor_json_translation_survives_reorder(client, admin):
    """Переклад іде за текстом: перестановка блоків його не збиває."""
    _login(client, admin)
    p = BlogPost(slug=f'p-{uuid4().hex[:6]}', title='T', status='published',
                 content=[{'type': 'paragraph', 'data': {'html': 'Перший.'}},
                          {'type': 'paragraph', 'data': {'html': 'Другий.'}}])
    db.session.add(p)
    db.session.flush()
    client.post(f'/admin/translations/blog_post/{p.id}', data={
        f'ru__content__{source_key("Перший.")}': 'Первый.',
        f'ru__content__{source_key("Другий.")}': 'Второй.',
    })

    # Адмін міняє блоки місцями і вставляє новий на початок.
    p.content = [{'type': 'paragraph', 'data': {'html': 'Новий.'}},
                 {'type': 'paragraph', 'data': {'html': 'Другий.'}},
                 {'type': 'paragraph', 'data': {'html': 'Перший.'}}]
    db.session.commit()

    ru = db.session.get(BlogPost, p.id).t('content', lang='ru')
    assert [b['data']['html'] for b in ru] == ['Новий.', 'Второй.', 'Первый.']


def test_editor_prefills_saved_translation(client, admin):
    _login(client, admin)
    c = _course()
    c.set_translation('ru', 'title', 'Збережено')
    db.session.commit()
    html = client.get(f'/admin/translations/course/{c.id}').get_data(as_text=True)
    assert 'Збережено' in html
