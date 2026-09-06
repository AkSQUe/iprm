"""Чотири реєстри, з яких раніше нікуди не можна було клікнути.

Блог: число «на модерації» веде в blog_comments, звужений по посту й
статусу (статус -- явно, хоч і дефолтний, щоб посилання читалось без
знання дефолтів). Сповіщення (дашборд): адресат/тригер/статус ведуть у
той самий журнал і за тим самим полем, за яким лінкується сам журнал (в
обох місцях статус -- клікабельна плашка). LiqPay: REG-<id> -> реєстр
проведення, ПІБ платника -> картка користувача. B2B: розмір команди ->
той самий реєстр за team_size, ПІБ -> реєстр користувачів за q (FK на
User в моделі немає, тож пошук по email), а email лишається mailto:.
"""
from tests.support.rbac import grant_role
import re
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.b2b_request import B2BRequest
from app.models.blog_comment import BlogComment
from app.models.blog_post import BlogPost
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.email_log import EmailLog
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'dd-{_uid()}@test.com', 'password123',
        first_name='D', last_name='D', email_confirmed=True,
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


# --- blog_list.html: лічильник "на модерації" -----------------------------

def test_pending_comments_count_links_to_blog_comments_by_post_and_status(client, admin):
    """`status=pending` у href навіть попри те, що це дефолт роуту --
    посилання мусить читатись без знання дефолтів цільового реєстру."""
    slug = f'dd-{_uid()}'
    post = BlogPost(title=f'Допис {_uid()}', slug=slug, status=BlogPost.STATUS_PUBLISHED)
    db.session.add(post)
    db.session.flush()
    comment = BlogComment(
        post_id=post.id, author_name='Читач', email='reader@test.com',
        body='Коментар', status=BlogComment.STATUS_PENDING,
    )
    db.session.add(comment)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/blog?q={slug}').get_data(as_text=True)
        # Jinja екранує '&' у href в '&amp;' -- порівнюємо з тим, що реально
        # потрапляє в HTML.
        href = f'/admin/blog/comments?post_id={post.id}&amp;status=pending'
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*1 на модерації', html,
        )
    finally:
        db.session.delete(db.session.merge(comment))
        db.session.delete(db.session.merge(post))
        db.session.commit()


def test_zero_pending_comments_stays_plain_text(client, admin):
    """Нуль (гілка з прочерком) не клікається -- розгортати там нічого."""
    slug = f'dd-{_uid()}'
    post = BlogPost(title=f'Допис {_uid()}', slug=slug, status=BlogPost.STATUS_PUBLISHED)
    db.session.add(post)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/blog?q={slug}').get_data(as_text=True)
        assert not re.search(rf'<a href="[^"]*post_id={post.id}[^"]*">', html)
        assert re.search(r'<span class="admin-text-muted">—</span>', html)
    finally:
        db.session.delete(db.session.merge(post))
        db.session.commit()


# --- notifications.html: дашборд, дзеркалить сам журнал --------------------

def test_dashboard_recipient_links_to_notifications_log_by_q(client, admin):
    email = f'dd-{_uid()}@test.com'
    log = EmailLog(
        to_email=email, subject='Тема', template_name='test.html',
        status='sent', trigger='test',
    )
    db.session.add(log)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get('/admin/notifications').get_data(as_text=True)
        href = f'/admin/notifications/log?q={email}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*{re.escape(email)}', html)
    finally:
        db.session.delete(db.session.merge(log))
        db.session.commit()


def test_dashboard_trigger_links_by_trigger_field_not_label(client, admin):
    """`trigger=test` у href, а не текст лейбла «Тест»."""
    email = f'dd-{_uid()}@test.com'
    log = EmailLog(
        to_email=email, subject='Тема', template_name='test.html',
        status='sent', trigger='test',
    )
    db.session.add(log)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get('/admin/notifications').get_data(as_text=True)
        href = '/admin/notifications/log?trigger=test'
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*Тест', html)
    finally:
        db.session.delete(db.session.merge(log))
        db.session.commit()


def test_dashboard_status_links_to_notifications_log_by_status(client, admin):
    email = f'dd-{_uid()}@test.com'
    log = EmailLog(
        to_email=email, subject='Тема', template_name='test.html',
        status='failed', trigger='test',
    )
    db.session.add(log)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get('/admin/notifications').get_data(as_text=True)
        href = '/admin/notifications/log?status=failed'
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*Помилка', html)
    finally:
        db.session.delete(db.session.merge(log))
        db.session.commit()


def test_journal_status_links_to_itself_by_status(client, admin):
    """Той самий журнал (notifications_log), лінк тепер і на статус -- як уже
    було на трігер, і як дашборд лінкує сюди ж."""
    email = f'dd-{_uid()}@test.com'
    log = EmailLog(
        to_email=email, subject='Тема', template_name='test.html',
        status='failed', trigger='test',
    )
    db.session.add(log)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get('/admin/notifications/log').get_data(as_text=True)
        href = '/admin/notifications/log?status=failed'
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*Помилка', html)
    finally:
        db.session.delete(db.session.merge(log))
        db.session.commit()


# --- liqpay.html: останні платежі -------------------------------------------

def test_reg_id_links_to_instance_registrations(client, admin):
    course = Course(title=f'Курс {_uid()}', slug=f'dd-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    payer = User.create_with_password(
        f'dd-{_uid()}@test.com', 'password123', first_name='Платник', last_name=_uid(),
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=payer.id, instance_id=inst.id, phone='+380671110002',
        specialty='T', workplace='Клініка', status='confirmed', payment_status='paid',
        payment_amount=Decimal('100.00'),
    )
    db.session.add(reg)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get('/admin/liqpay').get_data(as_text=True)
        href = f'/admin/instances/{inst.id}/registrations'
        assert re.search(rf'<a href="{re.escape(href)}">\s*REG-{reg.id}\s*</a>', html)
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(payer))
        db.session.commit()


def test_payer_full_name_links_to_user_detail(client, admin):
    course = Course(title=f'Курс {_uid()}', slug=f'dd-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    payer = User.create_with_password(
        f'dd-{_uid()}@test.com', 'password123', first_name='Унікальний', last_name=_uid(),
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=payer.id, instance_id=inst.id, phone='+380671110002',
        specialty='T', workplace='Клініка', status='confirmed', payment_status='paid',
        payment_amount=Decimal('100.00'),
    )
    db.session.add(reg)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get('/admin/liqpay').get_data(as_text=True)
        href = f'/admin/users/{payer.id}'
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*Унікальний\s*{re.escape(payer.last_name)}', html,
        )
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(payer))
        db.session.commit()


# --- b2b_requests.html ------------------------------------------------------

def _b2b(email, team_size='3-5'):
    req = B2BRequest(
        first_name='Контакт', last_name=_uid(), phone='+380671110003',
        email=email, team_size=team_size,
    )
    db.session.add(req)
    db.session.commit()
    return req


def test_b2b_team_size_links_to_b2b_requests_list_by_team_size(client, admin):
    """Значення поля `team_size` ('10+'), а не лейбл -- фільтр приймає код."""
    email = f'dd-{_uid()}@test.com'
    req = _b2b(email, team_size='10+')
    _login(client, admin)
    try:
        html = client.get(f'/admin/b2b-requests?q={email}').get_data(as_text=True)
        with client.application.test_request_context():
            from flask import url_for
            href = url_for('admin.b2b_requests_list', team_size='10+')
        href_in_html = href.replace('&', '&amp;')
        assert re.search(rf'<a href="{re.escape(href_in_html)}">\s*Понад 10', html)
    finally:
        db.session.delete(db.session.merge(req))
        db.session.commit()


def test_b2b_full_name_links_to_users_by_q(client, admin):
    """ПІБ -- відповідь на "чи є в нас акаунт цієї людини": FK на User в
    B2BRequest немає, а ПІБ не унікальне, тож звужуємо реєстр користувачів
    пошуком по email, а не переходом у чиюсь конкретну картку."""
    email = f'dd-{_uid()}@test.com'
    req = _b2b(email)
    _login(client, admin)
    try:
        html = client.get(f'/admin/b2b-requests?q={email}').get_data(as_text=True)
        href = f'/admin/users?q={email}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*{re.escape(req.full_name)}', html)
    finally:
        db.session.delete(db.session.merge(req))
        db.session.commit()


def test_b2b_email_cell_keeps_mailto(client, admin):
    """Email лишається основною дією комірки -- mailto: у списку заявок
    менеджер пише корпоративному ліду в один клік; лінк у реєстр користувачів
    переїхав на ПІБ, а не додався другим href в тій самій комірці."""
    email = f'dd-{_uid()}@test.com'
    req = _b2b(email)
    _login(client, admin)
    try:
        html = client.get(f'/admin/b2b-requests?q={email}').get_data(as_text=True)
        assert re.search(rf'<a href="mailto:{re.escape(email)}">\s*{re.escape(email)}', html)
    finally:
        db.session.delete(db.session.merge(req))
        db.session.commit()
