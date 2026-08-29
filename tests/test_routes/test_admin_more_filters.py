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
from app.models.webhook_delivery import WebhookDelivery

EMAIL_PREFIX = 'mf-'

# Маркер у target_url -- за ним прибираємо власні WebhookDelivery в teardown
# (таблиця без FK-дітей, тож досить одного DELETE, на відміну від User нижче).
WH_TARGET_MARKER = 'https://wh-test.example/'


@pytest.fixture(autouse=True)
def clean(app):
    """Порожні власні дописи/коментарі блогу і власні користувачі."""
    def _wipe():
        own_posts = db.session.query(BlogPost.id).filter(
            BlogPost.slug.like(f'{EMAIL_PREFIX}%'))
        # Явно, дитина перед батьком: BlogPost.comments оголошено з
        # passive_deletes=True (ORM свідомо покладається на БД-каскад), а
        # SQLite тестового прогону PRAGMA foreign_keys=ON всередині
        # транзакції не тримає -- каскад мовчки не спрацьовує, і коментарі
        # лишаються сирітками з post_id на видалений допис.
        BlogComment.query.filter(BlogComment.post_id.in_(own_posts)).delete(
            synchronize_session=False)
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


# ----------------------------- Webhook черга -----------------------------


@pytest.fixture(autouse=True)
def clean_webhooks(app):
    """Порожня власна частина webhook_deliveries.

    Таблиця -- лист (немає FK-дітей), тож на відміну від User/BlogPost вище
    досить одного DELETE за міткою в target_url.
    """
    def _wipe():
        WebhookDelivery.query.filter(
            WebhookDelivery.target_url.like(f'{WH_TARGET_MARKER}%')
        ).delete(synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


def _delivery(**kwargs):
    """WebhookDelivery за замовчуванням -- каталожна подія (курс), якщо
    виклик явно не задав event_type чи course_id (партнерська подія)."""
    kwargs.setdefault('event_uuid', uuid4().hex)
    kwargs.setdefault('target_url', WH_TARGET_MARKER + uuid4().hex[:8])
    kwargs.setdefault('status', 'pending')
    if 'event_type' not in kwargs and 'course_id' not in kwargs:
        kwargs.setdefault('course_id', 1)
        kwargs.setdefault('course_slug', 'course-' + uuid4().hex[:8])
        kwargs.setdefault('action', 'updated')
    delivery = WebhookDelivery(**kwargs)
    db.session.add(delivery)
    db.session.commit()
    return delivery


class TestWebhookQueueFilters:
    def test_search_narrows_by_course_slug(self, client, admin):
        marker = uuid4().hex[:10]
        target = _delivery(course_slug=f'course-{marker}')
        other = _delivery(course_slug='course-unrelated')

        _login(client, admin)
        body = client.get(f'/admin/webhooks?q={marker}').get_data(as_text=True)

        assert target.course_slug in body
        assert other.course_slug not in body

    def test_search_narrows_by_event_uuid(self, client, admin):
        target = _delivery()
        other = _delivery()

        _login(client, admin)
        body = client.get(f'/admin/webhooks?q={target.event_uuid}').get_data(as_text=True)

        assert target.event_uuid[:12] in body
        assert other.event_uuid[:12] not in body

    def test_event_type_catalog_shows_only_empty_event_type(self, client, admin):
        catalog = _delivery()  # event_type=None, курс/дія задані
        partner = _delivery(event_type='lead.created', target_url=WH_TARGET_MARKER + uuid4().hex[:8])

        _login(client, admin)
        body = client.get('/admin/webhooks?event_type=catalog').get_data(as_text=True)

        assert catalog.event_uuid[:12] in body
        assert partner.event_uuid[:12] not in body

    def test_second_page_keeps_status_and_q(self, client, admin):
        marker = 'whpage' + uuid4().hex[:6]
        for _ in range(26):
            _delivery(course_slug=f'{marker}-{uuid4().hex[:6]}', status='pending')

        _login(client, admin)
        page1 = client.get(
            f'/admin/webhooks?per_page=25&status=pending&q={marker}'
        ).get_data(as_text=True)
        page2 = client.get(
            f'/admin/webhooks?per_page=25&status=pending&q={marker}&page=2'
        ).get_data(as_text=True)

        assert 'page=2' in page1
        assert 'status=pending' in page1
        assert marker in page1

        page1_slugs = set(re.findall(rf'{re.escape(marker)}-\w{{6}}', page1))
        page2_slugs = set(re.findall(rf'{re.escape(marker)}-\w{{6}}', page2))
        assert len(page1_slugs) == 25
        assert len(page2_slugs) == 1
        assert not (page1_slugs & page2_slugs)

    def test_webhook_delete_redirects_with_saved_slice(self, client, admin):
        delivery = _delivery(status='failed')

        _login(client, admin)
        resp = client.post(
            f'/admin/webhooks/{delivery.id}/delete?status=failed&q=abc&page=2',
            follow_redirects=False,
        )

        assert resp.status_code == 302
        location = resp.headers['Location']
        assert 'status=failed' in location
        assert 'q=abc' in location
        assert 'page=2' in location
