"""Прогін панелі фільтрів (filter_bar) на реєстрах, що досі жили без неї.

Файл спільний для плану `docs/superpowers/plans/2026-08-29-admin-filter-bar-
rollout.md`: кожне з його завдань додає СЮДИ свою секцію, а не заводить
окремий файл --

  * Task 1 -- Коментарі блогу (тут);
  * Task 2 -- Webhook черга;
  * Task 3 -- Результати тестування по групі;
  * Task 4 -- Перф-прогони.

Секції незалежні одна від одної: спільне -- лише autouse-фікстура нижче,
що прибирає за собою власних User (SQLite без каскадів, а
/api/v1/participants?per_page=200 мовчки вважає, що більше 200 юзерів не
буває -- лишений тут акаунт валить TestParticipants ЛИШЕ в повному прогоні).
"""
import re
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.blog_comment import BlogComment
from app.models.blog_post import BlogPost
from app.models.medical_profile import MedicalProfile
from app.models.user import User

EMAIL_PREFIX = 'mf-'


@pytest.fixture(autouse=True)
def clean(app):
    """Порожні власні дописи/коментарі блогу і власні користувачі."""
    def _wipe():
        BlogPost.query.filter(BlogPost.slug.like(f'{EMAIL_PREFIX}%')).delete(
            synchronize_session=False)
        stale = [
            row.id for row in User.query.filter(
                User.email.like(f'{EMAIL_PREFIX}%@test.com')).all()
        ]
        if stale:
            for model in (AuthIdentity, MedicalProfile):
                model.query.filter(model.user_id.in_(stale)).delete(
                    synchronize_session=False)
            User.query.filter(User.id.in_(stale)).delete(
                synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'{EMAIL_PREFIX}{uuid4().hex[:8]}@test.com', 'password123',
        first_name='А', last_name='Адмін', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def _post(**kwargs):
    kwargs.setdefault('title', f'Допис {uuid4().hex[:6]}')
    post = BlogPost(slug=f'{EMAIL_PREFIX}{uuid4().hex[:8]}', **kwargs)
    db.session.add(post)
    db.session.commit()
    return post


def _comment(post, **kwargs):
    kwargs.setdefault('author_name', f'Автор {uuid4().hex[:4]}')
    kwargs.setdefault('email', f'{uuid4().hex[:8]}@example.com')
    kwargs.setdefault('body', 'Звичайний коментар без нічого особливого.')
    kwargs.setdefault('status', BlogComment.STATUS_PENDING)
    comment = BlogComment(post_id=post.id, **kwargs)
    db.session.add(comment)
    db.session.commit()
    return comment


# --------------------------- Коментарі блогу ---------------------------


class TestBlogCommentsFilters:
    def test_search_narrows_to_matching_comment(self, client, admin):
        post = _post()
        target = _comment(post, author_name='Незвичне Прізвище')
        other = _comment(post, author_name='Хтось Інший')

        _login(client, admin)
        body = client.get('/admin/blog/comments?q=Незвичне').get_data(as_text=True)

        assert target.author_name in body
        assert other.author_name not in body

    def test_post_filter_shows_only_its_comments(self, client, admin):
        post_a = _post(title='Допис А')
        post_b = _post(title='Допис Б')
        own = _comment(post_a, author_name='Коментар допису А')
        foreign = _comment(post_b, author_name='Коментар допису Б')

        _login(client, admin)
        body = client.get(f'/admin/blog/comments?post_id={post_a.id}').get_data(as_text=True)

        assert own.author_name in body
        assert foreign.author_name not in body

    def test_second_page_carries_status_and_filter(self, client, admin):
        post = _post()
        # 26 коментарів під одним пошуковим словом -- при per_page=25 це
        # рівно дві сторінки, і на другій лишається один інакший рядок.
        for _ in range(26):
            _comment(post, author_name='Сторінковий-' + uuid4().hex[:6])

        _login(client, admin)
        page1 = client.get(
            '/admin/blog/comments?per_page=25&q=Сторінковий'
        ).get_data(as_text=True)
        page2 = client.get(
            '/admin/blog/comments?per_page=25&q=Сторінковий&page=2'
        ).get_data(as_text=True)

        assert 'page=2' in page1
        assert 'status=pending' in page1
        assert 'q=' in page1

        # Рядки на сторінках різні: 25 авторів на першій, 1 -- на другій, і
        # той один не мусить траплятись на першій.
        page1_authors = set(re.findall(r'Сторінковий-\w{6}', page1))
        page2_authors = set(re.findall(r'Сторінковий-\w{6}', page2))
        assert len(page1_authors) == 25
        assert len(page2_authors) == 1
        assert not (page1_authors & page2_authors)

    def test_empty_filtered_result_says_nothing_found(self, client, admin):
        post = _post()
        _comment(post)

        _login(client, admin)
        body = client.get('/admin/blog/comments?q=НемаєТакогоНіде').get_data(as_text=True)

        assert 'Нічого не знайдено' in body
        assert 'Коментарів немає' not in body

    def test_empty_without_filter_says_no_comments(self, client, admin):
        _login(client, admin)
        body = client.get('/admin/blog/comments?status=spam').get_data(as_text=True)

        assert 'Коментарів немає' in body
