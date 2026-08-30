"""Люди й тарифи (раунд 3, задача 2).

Сторінка повернення коштів досі не мала жодного входу в картку покупця,
хоч рішення про повернення ухвалюють саме по людині. У реєстрах тарифів
назва тарифу веде в той самий редактор, що й кнопка дії поруч -- це той
самий виклик з тими самими аргументами, просто ще один вхід у нього.

Кожен тест перевіряє САМЕ тег навколо значення: інакше перевірка пройшла
б і на нерозгорнутому тексті.
"""
import re
from decimal import Decimal
from uuid import uuid4

import pytest
from flask import url_for

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_tariff import CourseTariff
from app.models.instance_tariff import InstanceTariff
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'rt-{_uid()}@test.com', 'password123',
        first_name='R', last_name='T', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_refund_form_buyer_links_to_user_detail(client, admin, app):
    buyer = User.create_with_password(
        f'rt-{_uid()}@test.com', 'password123',
        first_name='Наталя', last_name='Стеценко', email_confirmed=True,
    )
    db.session.flush()
    course = Course(title=f'Курс {_uid()}', slug=f'rt-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=buyer.id, instance_id=inst.id, phone='+380671110006',
        specialty='T', workplace='Клініка', status='confirmed', payment_status='paid',
        payment_amount=Decimal('1000'),
    )
    db.session.add(reg)
    db.session.commit()
    _login(client, admin)
    with app.test_request_context():
        get_url = url_for('admin.refund_form', kind='registration', order_id=reg.id)
        href = url_for('admin.user_detail', user_id=buyer.id)
    try:
        html = client.get(get_url).get_data(as_text=True)
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*{re.escape(buyer.first_name)}\s*{re.escape(buyer.last_name)}\s*</a>',
            html,
        )
        # Email лишається текстом поруч, а не всередині посилання.
        assert not re.search(
            rf'<a href="{re.escape(href)}">[^<]*{re.escape(buyer.email)}',
            html,
        )
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(buyer))
        db.session.commit()


def test_course_tariff_name_links_to_edit(client, admin, app):
    course = Course(title=f'Курс {_uid()}', slug=f'rt-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    name = f'Тариф {_uid()}'
    tariff = CourseTariff(
        course_id=course.id, name=name, price=Decimal('1000'),
        sort_order=0, is_active=True,
    )
    db.session.add(tariff)
    db.session.commit()
    _login(client, admin)
    with app.test_request_context():
        list_url = url_for('admin.course_tariffs', course_id=course.id)
        href = url_for('admin.course_tariff_edit', tariff_id=tariff.id)
    try:
        html = client.get(list_url).get_data(as_text=True)
        assert re.search(rf'<a href="{re.escape(href)}">\s*<strong>\s*{re.escape(name)}\s*</strong>\s*</a>', html)
    finally:
        # Курс каскадно забирає й тариф (cascade='all, delete-orphan').
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_instance_tariff_name_links_to_edit(client, admin, app):
    course = Course(title=f'Курс {_uid()}', slug=f'rt-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    name = f'Тариф {_uid()}'
    tariff = InstanceTariff(
        instance_id=inst.id, name=name, price=Decimal('1000'),
        sort_order=0, is_active=True,
    )
    db.session.add(tariff)
    db.session.commit()
    _login(client, admin)
    with app.test_request_context():
        list_url = url_for('admin.instance_tariffs', instance_id=inst.id)
        href = url_for('admin.instance_tariff_edit', tariff_id=tariff.id)
    try:
        html = client.get(list_url).get_data(as_text=True)
        assert re.search(rf'<a href="{re.escape(href)}">\s*<strong>\s*{re.escape(name)}\s*</strong>\s*</a>', html)
    finally:
        # Проведення каскадно забирає й тариф (cascade='all, delete-orphan').
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.commit()
