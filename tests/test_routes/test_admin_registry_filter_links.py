"""Реєстри, де значення веде у ВЛАСНИЙ фільтр (той самий реєстр, звужений
цим самим значенням) -- третій раунд.

Коментарі блогу: ПІБ автора -> users(q=email), лише коли email заповнений
(модель це допускає, коментар анонімний); бейдж статусу -> blog_comments
за полем `status`, не лейблом. Черга подій Meta: бейдж статусу і джерело --
кожен у свій фільтр ТОГО Ж реєстру; та сама пара на картці ліда веде в
РЕЄСТР подій (власного фільтра там нема). Онлайн-курси -- пастка: колонка
статусу показує ВІДДАЛЕНИЙ стан Sintegrum, а фільтр `status` звужує за
ЛОКАЛЬНИМ станом публікації/готовності, тож лінкується лише гілка «Зник»
(обидва виміри там -- те саме поле `is_vanished`) і обидві гілки колонки
«Готовність» (той самий предикат, що й фільтр); дві гілки стану Sintegrum
лишаються текстом -- негативний сторож нижче це й перевіряє. Резервування
матеріалів: бейдж статусу -> materials_overview за полем `status`.
"""
from tests.support.rbac import grant_role
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from flask import url_for

from app.extensions import db
from app.models.blog_comment import BlogComment
from app.models.blog_post import BlogPost
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_reservation import MaterialReservation, MaterialReservationStatus
from app.models.meta_lead import MetaLead, MetaLeadEvent
from app.models.online_course import OnlineCourse
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'rf-{_uid()}@test.com', 'password123',
        first_name='R', last_name='F', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


# --- blog_comments.html -----------------------------------------------------

def _comment(email='', status=BlogComment.STATUS_PENDING, author_name=None):
    slug = f'rf-{_uid()}'
    post = BlogPost(title=f'Допис {_uid()}', slug=slug, status=BlogPost.STATUS_PUBLISHED)
    db.session.add(post)
    db.session.flush()
    comment = BlogComment(
        post_id=post.id, author_name=author_name or f'Автор{_uid()}',
        email=email, body='Текст коментаря', status=status,
    )
    db.session.add(comment)
    db.session.commit()
    return post, comment


def test_comment_author_with_email_links_to_users_by_q(client, admin, app):
    email = f'rf-{_uid()}@test.com'
    post, comment = _comment(email=email)
    _login(client, admin)
    try:
        html = client.get(f'/admin/blog/comments?post_id={post.id}&status=all').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.users', q=email)
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*<strong>\s*{re.escape(comment.author_name)}', html,
        )
    finally:
        db.session.delete(db.session.merge(comment))
        db.session.delete(db.session.merge(post))
        db.session.commit()


def test_comment_author_without_email_stays_plain_text(client, admin):
    """Анонімний коментар без email -- шукати в users нема за чим."""
    post, comment = _comment(email=None)
    _login(client, admin)
    try:
        html = client.get(f'/admin/blog/comments?post_id={post.id}&status=all').get_data(as_text=True)
        m = re.search(rf'(<a[^>]*>)?\s*<strong>\s*{re.escape(comment.author_name)}\s*</strong>', html)
        assert m, 'рядок коментаря не знайдено'
        assert m.group(1) is None, 'без email ПІБ не має бути посиланням'
        assert '/admin/users?q=' not in html
    finally:
        db.session.delete(db.session.merge(comment))
        db.session.delete(db.session.merge(post))
        db.session.commit()


def test_comment_status_links_to_blog_comments_by_status_field(client, admin, app):
    """`status`, поле моделі, а не `status_label` -- фільтр приймає код."""
    post, comment = _comment(email=f'rf-{_uid()}@test.com', status=BlogComment.STATUS_SPAM)
    _login(client, admin)
    try:
        html = client.get(f'/admin/blog/comments?post_id={post.id}&status=all').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.blog_comments', status='spam')
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*Спам', html)
    finally:
        db.session.delete(db.session.merge(comment))
        db.session.delete(db.session.merge(post))
        db.session.commit()


# --- meta_lead_events.html: сира черга ---------------------------------------

def _event(leadgen_id=None, status=MetaLeadEvent.STATUS_FAILED,
           source=MetaLeadEvent.SOURCE_MANUAL, lead_id=None):
    event = MetaLeadEvent(
        leadgen_id=leadgen_id or f'rf-{_uid()}', received_at=datetime.now(timezone.utc),
        status=status, source=source, lead_id=lead_id,
    )
    db.session.add(event)
    db.session.commit()
    return event


def test_event_status_links_to_meta_lead_events_by_status(client, admin, app):
    event = _event()
    _login(client, admin)
    try:
        html = client.get(f'/admin/meta-leads/events?q={event.leadgen_id}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.meta_lead_events', status='failed')
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*Помилка', html)
    finally:
        db.session.delete(db.session.merge(event))
        db.session.commit()


def test_event_source_links_to_meta_lead_events_by_source_field(client, admin, app):
    """`source`, поле моделі, а не лейбл -- фільтр приймає код."""
    event = _event(source=MetaLeadEvent.SOURCE_MANUAL)
    _login(client, admin)
    try:
        html = client.get(f'/admin/meta-leads/events?q={event.leadgen_id}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.meta_lead_events', source='manual')
        assert re.search(rf'<a href="{re.escape(href)}">\s*Вручну', html)
    finally:
        db.session.delete(db.session.merge(event))
        db.session.commit()


# --- meta_lead_detail.html: подій ліда, без власного фільтра ----------------

def _lead(leadgen_id):
    lead = MetaLead(
        leadgen_id=leadgen_id, created_time=datetime.now(timezone.utc),
        first_name='Лід', last_name=_uid(),
    )
    db.session.add(lead)
    db.session.commit()
    return lead


def test_lead_detail_event_status_and_source_link_to_events_registry(client, admin, app):
    """Сторінка ліда власного фільтра не має -- обидва значення ведуть у
    РЕЄСТР подій з тим самим фільтром, що й там."""
    leadgen_id = f'rf-{_uid()}'
    lead = _lead(leadgen_id)
    event = _event(leadgen_id=leadgen_id, status=MetaLeadEvent.STATUS_RETRYING,
                    source=MetaLeadEvent.SOURCE_RECONCILE, lead_id=lead.id)
    _login(client, admin)
    try:
        html = client.get(f'/admin/meta-leads/{lead.id}').get_data(as_text=True)
        with app.test_request_context():
            status_href = url_for('admin.meta_lead_events', status='retrying')
            source_href = url_for('admin.meta_lead_events', source='reconcile')
        assert re.search(rf'<a href="{re.escape(status_href)}">\s*<span[^>]*>\s*Повтор', html)
        assert re.search(rf'<a href="{re.escape(source_href)}">\s*reconcile', html)
    finally:
        db.session.delete(db.session.merge(event))
        db.session.delete(db.session.merge(lead))
        db.session.commit()


# --- online_courses.html: пастка різних вимірів ------------------------------

def _sid():
    """sintegrum_id унікальний і достатньо великий, щоб не перетнутись із
    реальними даними (стовпець integer, unique)."""
    return int(uuid4().int % 900_000_000) + 100_000_000


def _online_course(sintegrum_id, remote_status, is_vanished=False, price=None,
                    is_published=False):
    course = OnlineCourse(
        sintegrum_id=sintegrum_id, remote_name=f'Курс {_uid()}',
        slug=f'rf-{_uid()}', remote_status=remote_status,
        is_vanished=is_vanished, price=price, is_published=is_published,
    )
    db.session.add(course)
    db.session.commit()
    return course


def test_vanished_branch_links_to_status_vanished(client, admin, app):
    """`is_vanished` -- єдина гілка колонки стану Sintegrum, де вимір
    співпадає з локальним фільтром: те саме поле з обох боків."""
    course = _online_course(sintegrum_id=_sid(),
                             remote_status=0, is_vanished=True)
    _login(client, admin)
    try:
        html = client.get(f'/admin/online-courses?q={course.slug}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.online_courses_list', status='vanished')
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span class="badge badge--danger">\s*Зник', html)
    finally:
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_remote_active_branch_stays_plain_text(client, admin):
    """Колонка «Стан у Sintegrum» показує ВІДДАЛЕНИЙ стан, а фільтр `status`
    звужує за ЛОКАЛЬНИМ станом публікації/готовності -- різні виміри, лінка
    тут бути не може."""
    course = _online_course(sintegrum_id=_sid(),
                             remote_status=1, is_vanished=False)
    _login(client, admin)
    try:
        html = client.get(f'/admin/online-courses?q={course.slug}').get_data(as_text=True)
        m = re.search(
            rf'<td>{course.sintegrum_id}</td>\s*<td>\s*(<a[^>]*>)?\s*'
            rf'<span class="badge badge--\w+">\s*Активний', html,
        )
        assert m, 'рядок курсу не знайдено'
        assert m.group(1) is None, 'стан Sintegrum не має клікатись -- це не той вимір, що фільтр'
    finally:
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_remote_inactive_branch_stays_plain_text(client, admin):
    course = _online_course(sintegrum_id=_sid(),
                             remote_status=0, is_vanished=False)
    _login(client, admin)
    try:
        html = client.get(f'/admin/online-courses?q={course.slug}').get_data(as_text=True)
        m = re.search(
            rf'<td>{course.sintegrum_id}</td>\s*<td>\s*(<a[^>]*>)?\s*'
            rf'<span class="badge badge--\w+">\s*Неактивний', html,
        )
        assert m, 'рядок курсу не знайдено'
        assert m.group(1) is None, 'стан Sintegrum не має клікатись -- це не той вимір, що фільтр'
    finally:
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_ready_branch_links_to_status_ready(client, admin, app):
    """`can_be_published` -- той самий предикат, що фільтр `status=ready`."""
    course = _online_course(sintegrum_id=_sid(),
                             remote_status=1, is_vanished=False, price=100)
    _login(client, admin)
    try:
        html = client.get(f'/admin/online-courses?q={course.slug}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.online_courses_list', status='ready')
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span class="badge badge--active">\s*Готовий', html)
    finally:
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_incomplete_branch_links_to_status_incomplete(client, admin, app):
    """Без ефективної ціни курс "Бракує даних" -- та сама умова, що
    `status=incomplete` (заперечення `publishable_clause`)."""
    course = _online_course(sintegrum_id=_sid(),
                             remote_status=1, is_vanished=False, price=None)
    _login(client, admin)
    try:
        html = client.get(f'/admin/online-courses?q={course.slug}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.online_courses_list', status='incomplete')
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*<span class="badge badge--draft"[^>]*>\s*Бракує даних', html,
        )
    finally:
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_published_branch_links_to_status_published(client, admin, app):
    """`is_published` -- те саме поле, за яким фільтр `status` звужує на
    published/hidden: на відміну від «Стану у Sintegrum», тут колонка й
    фільтр міряють один і той самий вимір."""
    course = _online_course(sintegrum_id=_sid(),
                             remote_status=1, is_vanished=False, price=100,
                             is_published=True)
    _login(client, admin)
    try:
        html = client.get(f'/admin/online-courses?q={course.slug}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.online_courses_list', status='published')
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span class="badge badge--published">\s*Опубліковано', html)
    finally:
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_hidden_branch_links_to_status_hidden(client, admin, app):
    course = _online_course(sintegrum_id=_sid(),
                             remote_status=1, is_vanished=False, price=100,
                             is_published=False)
    _login(client, admin)
    try:
        html = client.get(f'/admin/online-courses?q={course.slug}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.online_courses_list', status='hidden')
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span class="badge badge--draft">\s*Приховано', html)
    finally:
        db.session.delete(db.session.merge(course))
        db.session.commit()


# --- materials_overview.html -------------------------------------------------

def test_reservation_status_links_to_materials_overview_by_status_field(client, admin, app):
    """`status`, поле моделі, а не `status_label`. Кількість позицій
    (`r.items|length`) лишається текстом -- рядок уже двічі веде в
    `instance_materials` (назва заходу, кнопка дій), третій лінк в ту саму
    ціль порушив би принцип "дві комірки одного рядка не в одне місце".

    Реєстр не має пошуку за текстом -- звужуємо унікальним днем заходу
    (`date_from`/`date_to`), щоб на сторінці лишився рівно наш рядок.
    """
    day_offset = 4000 + int(_uid(), 16) % 3000
    start = datetime.now(timezone.utc) + timedelta(days=day_offset)
    course = Course(title=f'Матеріали {_uid()}', slug=f'rf-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline',
                          start_date=start)
    db.session.add(inst)
    db.session.flush()
    reservation = MaterialReservation(
        instance_id=inst.id, external_ref=f'rf-{_uid()}',
        status=MaterialReservationStatus.EXPIRED,
    )
    db.session.add(reservation)
    db.session.commit()
    _login(client, admin)
    try:
        day = start.strftime('%Y-%m-%d')
        html = client.get(f'/admin/materials?date_from={day}&date_to={day}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.materials_overview', status='expired')
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*Протерміновано', html)
    finally:
        db.session.rollback()
        MaterialReservation.query.filter_by(id=reservation.id).delete()
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.commit()
