"""П'ять реєстрів адмінки: сутність у клітинці веде у свою картку.

Кожен тест перевіряє рівно одне посилання на своєму реєстрі: тренер курсу,
курс відгуку, курс комплекту матеріалів, slug курсу в доставці webhook і
ПІБ отримувача сертифіката (лише коли є зв'язок з користувачем -- знімок
рядком `event_title`/`recipient_name` без зв'язку нікуди не веде).
"""
from tests.support.rbac import grant_role
import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_kit import MaterialKit
from app.models.registration import EventRegistration
from app.models.review import Review
from app.models.trainer import Trainer
from app.models.user import User
from app.models.webhook_delivery import WebhookDelivery


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'el-{_uid()}@test.com', 'password123',
        first_name='E', last_name='L', email_confirmed=True,
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


def test_course_trainer_links_to_trainer_edit(client, admin):
    trainer = Trainer(full_name=f'Тренер {_uid()}', slug=f'el-{_uid()}')
    db.session.add(trainer)
    db.session.flush()
    course = Course(title=f'Курс {_uid()}', slug=f'el-{_uid()}',
                     is_active=True, trainer_id=trainer.id)
    db.session.add(course)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(
            f'/admin/courses?trainer_id={trainer.id}',
        ).get_data(as_text=True)
        href = f'/admin/trainers/{trainer.id}/edit'
        assert re.search(rf'<a href="{re.escape(href)}">\s*{re.escape(trainer.full_name)}', html)
    finally:
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(trainer))
        db.session.commit()


def test_review_course_links_to_course_edit(client, admin):
    course = Course(title=f'Курс {_uid()}', slug=f'el-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    review = Review(author_name=f'Автор {_uid()}', text='Текст відгуку',
                     rating=5, is_published=True, course_id=course.id)
    db.session.add(review)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(
            f'/admin/reviews?course_id={course.id}',
        ).get_data(as_text=True)
        href = f'/admin/courses/{course.id}/edit'
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*{re.escape(course.title)}',
            html,
        )
    finally:
        db.session.delete(db.session.merge(review))
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_material_kit_course_links_to_course_edit(client, admin):
    course = Course(title=f'Курс {_uid()}', slug=f'el-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    kit = MaterialKit(name=f'Комплект {_uid()}', course_id=course.id)
    db.session.add(kit)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get('/admin/material-kits').get_data(as_text=True)
        href = f'/admin/courses/{course.id}/edit'
        assert re.search(rf'<a href="{re.escape(href)}">\s*{re.escape(course.title)}', html)
    finally:
        db.session.delete(db.session.merge(kit))
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_webhook_course_slug_links_to_courses_list(client, admin):
    slug = f'el-{_uid()}'
    course = Course(title=f'Курс {_uid()}', slug=slug, is_active=True)
    db.session.add(course)
    db.session.flush()
    delivery = WebhookDelivery(
        course_id=course.id, course_slug=slug, action='updated',
        event_uuid=uuid4().hex, target_url='https://partner.example/hook',
        status='pending',
    )
    db.session.add(delivery)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/webhooks?q={slug}').get_data(as_text=True)
        href = f'/admin/courses?q={slug}'
        assert re.search(rf'<a href="{re.escape(href)}"[^>]*>\s*{re.escape(slug)}', html)
    finally:
        db.session.delete(db.session.merge(delivery))
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_certificate_recipient_links_to_user_detail(client, admin):
    user = User.create_with_password(
        f'p-{_uid()}@test.com', 'password123',
        first_name='Отримувач', last_name=_uid(), email_confirmed=True,
    )
    db.session.flush()
    course = Course(title=f'Курс {_uid()}', slug=f'el-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='completed', event_format='offline',
                          start_date=datetime.now(timezone.utc))
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380671110003',
        specialty='T', workplace='Клініка', status='confirmed', payment_status='paid',
    )
    db.session.add(reg)
    db.session.flush()
    recipient_name = f'{user.first_name} {user.last_name}'
    cert = Certificate(
        registration_id=reg.id, user_id=user.id, number=f'el-{_uid()}',
        recipient_name=recipient_name, event_title=course.title,
        pdf_path=f'certificates/el-{_uid()}.pdf',
    )
    db.session.add(cert)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/certificates?q={recipient_name}').get_data(as_text=True)
        href = f'/admin/users/{user.id}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*{re.escape(recipient_name)}', html)
    finally:
        db.session.delete(db.session.merge(cert))
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(user))
        db.session.commit()
