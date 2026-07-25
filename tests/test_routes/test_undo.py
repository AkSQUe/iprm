"""Undo замість підтвердження: видалення -> тост "Повернути" -> відкат.

Перевіряємо повний ланцюг: дія кладе пропозицію в сесію, наступна сторінка
віддає її JS-острівцем, відкат повертає рядок, а фонова чистка через
витримку прибирає його назавжди.
"""
from datetime import timedelta
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.blog_comment import BlogComment
from app.models.blog_post import BlogPost
from app.models.mixins import utcnow
from app.models.review import Review
from app.models.user import User


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'u-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='U', last_name='N', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_review_delete_offers_undo_and_restores(client, admin):
    rev = Review(author_name='Відкатний', text='текст', rating=5, is_published=True)
    db.session.add(rev)
    db.session.flush()
    _login(client, admin)

    client.post(f'/admin/reviews/{rev.id}/delete')
    with client.session_transaction() as s:
        offer = s.get('undo_offer')
    assert offer and offer['url'].endswith(f'/admin/reviews/{rev.id}/restore')

    # Наступна сторінка віддає пропозицію фронтенду і гасить її в сесії.
    page = client.get('/admin/reviews')
    assert b'iprm-undo-data' in page.data
    with client.session_transaction() as s:
        assert 'undo_offer' not in s

    client.post(f'/admin/reviews/{rev.id}/restore')
    assert not db.session.get(Review, rev.id).is_deleted


def test_offer_survives_page_render_before_delete(client, admin):
    """Сторінка, відкрита ДО видалення, не має гасити майбутню пропозицію.

    Пропозиція кешується на час запиту. Якщо кеш живе на g, під зовнішнім
    app-контекстом (тести, скрипти) він спільний для всіх запитів, і
    закешоване "пропозиції немає" з першого рендеру перекрило б тост.
    """
    rev = Review(author_name='Порядок', text='текст', rating=5)
    db.session.add(rev)
    db.session.flush()
    _login(client, admin)

    assert client.get('/admin/reviews').status_code == 200   # рендер до дії
    client.post(f'/admin/reviews/{rev.id}/delete')
    assert b'iprm-undo-data' in client.get('/admin/reviews').data


def test_deleted_review_hidden_from_public(client, admin):
    rev = Review(author_name='Схований', text='текст', rating=5, is_published=True)
    db.session.add(rev)
    db.session.flush()
    _login(client, admin)
    client.post(f'/admin/reviews/{rev.id}/delete')
    assert 'Схований'.encode() not in client.get('/').data


def test_comment_delete_takes_replies_and_restore_returns_them(client, admin):
    post = BlogPost(slug=f'p-{uuid4().hex[:6]}', title='T', status='published')
    db.session.add(post)
    db.session.flush()
    root = BlogComment(post_id=post.id, author_name='Корінь', body='root',
                       status=BlogComment.STATUS_APPROVED)
    db.session.add(root)
    db.session.flush()
    reply = BlogComment(post_id=post.id, parent_id=root.id, author_name='Відповідь',
                        body='reply', status=BlogComment.STATUS_APPROVED)
    db.session.add(reply)
    db.session.flush()
    _login(client, admin)

    client.post(f'/admin/blog/comments/{root.id}/delete')
    assert db.session.get(BlogComment, root.id).is_deleted
    assert db.session.get(BlogComment, reply.id).is_deleted, 'гілка ховається цілком'

    client.post(f'/admin/blog/comments/{root.id}/restore')
    assert not db.session.get(BlogComment, root.id).is_deleted
    assert not db.session.get(BlogComment, reply.id).is_deleted


def test_restore_twice_is_reported_not_silent(client, admin):
    rev = Review(author_name='Двічі', text='текст', rating=5)
    db.session.add(rev)
    db.session.flush()
    _login(client, admin)
    client.post(f'/admin/reviews/{rev.id}/delete')
    client.post(f'/admin/reviews/{rev.id}/restore')
    r = client.post(f'/admin/reviews/{rev.id}/restore', follow_redirects=True)
    assert 'уже не можна повернути'.encode() in r.data


def test_purge_removes_only_expired(app, admin):
    from app.services.soft_delete_purge import purge_expired

    fresh = Review(author_name='Свіжий', text='t', rating=5)
    stale = Review(author_name='Старий', text='t', rating=5)
    db.session.add_all([fresh, stale])
    db.session.flush()
    fresh.deleted_at = utcnow() - timedelta(days=1)
    stale.deleted_at = utcnow() - timedelta(days=90)
    db.session.flush()

    stats = purge_expired(retention_days=30)
    assert stats['reviews'] == 1
    assert db.session.get(Review, fresh.id) is not None
    assert db.session.get(Review, stale.id) is None
