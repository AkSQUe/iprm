"""Інтеграційні тести блогу: збереження контенту, рендер, коментарі, прев'ю."""
from tests.support.rbac import grant_role
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.user import User
from app.models.blog_post import BlogPost
from app.models.blog_comment import BlogComment


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'admin-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def _published(slug='post', title='Допис'):
    p = BlogPost(
        slug=slug, title=title, status=BlogPost.STATUS_PUBLISHED,
        published_at=datetime.now(timezone.utc), content=[],
    )
    db.session.add(p)
    db.session.flush()
    return p


class TestAdminBlog:
    def test_new_form_has_single_hidden_fields(self, client, admin):
        """Регресія: hidden_tag() дублював HiddenField -> контент губився.
        Поля content/cover_media_id мають рендеритися РІВНО один раз."""
        _login(client, admin)
        html = client.get('/admin/blog/new').get_data(as_text=True)
        assert html.count('name="content"') == 1
        assert html.count('name="cover_media_id"') == 1

    def test_create_saves_content_blocks(self, client, admin):
        _login(client, admin)
        content = json.dumps([
            {'type': 'heading', 'data': {'level': 2, 'text': 'Заголовок'}},
            {'type': 'paragraph', 'data': {'html': 'Текст'}},
        ])
        r = client.post('/admin/blog/new', data={
            'title': 'Мій допис', 'status': 'draft', 'content': content,
        })
        assert r.status_code == 302
        post = BlogPost.query.filter_by(title='Мій допис').first()
        assert post is not None
        assert len(post.content) == 2

    def test_preview_renders_draft(self, client, admin):
        _login(client, admin)
        p = BlogPost(slug='draft', title='Чернетка', status='draft',
                     content=[{'type': 'paragraph', 'data': {'html': 'ЧЕРНОВИК'}}])
        db.session.add(p)
        db.session.flush()
        r = client.get(f'/admin/blog/{p.id}/preview')
        assert r.status_code == 200
        assert 'ЧЕРНОВИК' in r.get_data(as_text=True)


class TestPublicBlog:
    def test_published_renders(self, client):
        _published(slug='hello', title='Привіт')
        r = client.get('/blog/hello')
        assert r.status_code == 200
        assert 'Привіт' in r.get_data(as_text=True)

    def test_draft_returns_404(self, client):
        p = BlogPost(slug='secret', title='Чернетка', status='draft', content=[])
        db.session.add(p)
        db.session.flush()
        assert client.get('/blog/secret').status_code == 404

    def test_feed_ok(self, client):
        _published(slug='f1')
        r = client.get('/blog/feed.xml')
        assert r.status_code == 200
        assert 'application/rss+xml' in r.mimetype or 'rss' in r.get_data(as_text=True)

    def test_huge_page_returns_200_not_500(self, client):
        """`/blog/` не потребує логіна: раніше величезний ?page= ішов в
        OFFSET як параметр драйвера й падав 500 (OverflowError/"bigint out
        of range") анонімному відвідувачу без жодного захисту."""
        r = client.get('/blog/?page=99999999999999999999')
        assert r.status_code == 200


class TestComments:
    def test_honeypot_silently_drops(self, client):
        p = _published(slug='c1')
        client.post('/blog/c1/comment', data={
            'name': 'Bot', 'body': 'spam', 'website': 'http://x',
        })
        assert BlogComment.query.count() == 0

    def test_submit_is_pending_and_hidden(self, client):
        p = _published(slug='c2')
        client.post('/blog/c2/comment', data={'name': 'Іван', 'body': 'Текст'})
        c = BlogComment.query.one()
        assert c.status == BlogComment.STATUS_PENDING
        assert 'Текст' not in client.get('/blog/c2').get_data(as_text=True)

    def test_approved_is_visible(self, client):
        p = _published(slug='c3')
        c = BlogComment(post_id=p.id, author_name='A', body='ВИДНО',
                        status=BlogComment.STATUS_APPROVED)
        db.session.add(c)
        db.session.flush()
        assert 'ВИДНО' in client.get('/blog/c3').get_data(as_text=True)

    def test_orphan_reply_promoted_to_root(self, client):
        """Схвалена відповідь під несхваленим батьком має показуватися."""
        p = _published(slug='c4')
        parent = BlogComment(post_id=p.id, author_name='P', body='parent',
                             status=BlogComment.STATUS_PENDING)
        db.session.add(parent)
        db.session.flush()
        child = BlogComment(post_id=p.id, parent_id=parent.id, author_name='C',
                            body='ОРФАН', status=BlogComment.STATUS_APPROVED)
        db.session.add(child)
        db.session.flush()
        assert 'ОРФАН' in client.get('/blog/c4').get_data(as_text=True)
