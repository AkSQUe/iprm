"""Реєстр користувачів адмінки: ПІБ і число реєстрацій ведуть у картку.

Обидва посилання ведуть в один і той самий `user_detail`. Перелік там
ширший за число поруч: картка показує ВСІ реєстрації людини, включно зі
скасованими, а `registration_count` (User.with_registration_count) їх не
рахує -- статусного фільтра, що дав би рівно те саме число, просто немає.
Зате число точно про того самого користувача, на відміну від пошуку по
email, який ловить чужі адреси-підрядки.
"""
import re
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'ul-{_uid()}@test.com', 'password123',
        first_name='U', last_name='L', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _list_html(client, email):
    """Список, звужений до одного тестового користувача.

    Сесія тестів ділить одну БД, тож фільтр за унікальним email потрібен так
    само, як `course_id` у test_admin_seats.py: без нього рядок чужого
    користувача робив би перевірку випадковою.
    """
    return client.get(f'/admin/users?q={email}').get_data(as_text=True)


def test_full_name_links_to_user_detail(client, admin):
    email = f'ul-{_uid()}@test.com'
    user = User.create_with_password(
        email, 'password123', first_name='Тест', last_name='Юзерів',
    )
    db.session.commit()
    _login(client, admin)
    try:
        html = _list_html(client, email)
        href = f'/admin/users/{user.id}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*Тест Юзерів', html)
    finally:
        db.session.delete(db.session.merge(user))
        db.session.commit()


def test_registration_count_links_to_user_detail(client, admin):
    """Число реєстрацій -- вхід у ту саму картку.

    ПІБ у сусідній клітинці веде туди ж, тож перевіряємо саме тег навколо
    числа: інакше тест пройшов би й на неклікабельній цифрі.
    """
    email = f'ul-{_uid()}@test.com'
    user = User.create_with_password(
        email, 'password123', first_name='Тест', last_name='Реєстрований',
    )
    db.session.flush()
    course = Course(title=f'Курс {_uid()}', slug=f'ul-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380671110002',
        specialty='T', workplace='Клініка', status='pending', payment_status='unpaid',
    )
    db.session.add(reg)
    db.session.commit()
    _login(client, admin)
    try:
        html = _list_html(client, email)
        href = f'/admin/users/{user.id}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*1\s*</a>', html)
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(user))
        db.session.commit()


def test_zero_registrations_stays_plain_text(client, admin):
    """Нуль не клікається -- розгортати там нічого."""
    email = f'ul-{_uid()}@test.com'
    user = User.create_with_password(
        email, 'password123', first_name='Нуль', last_name='Реєстрацій',
    )
    db.session.commit()
    _login(client, admin)
    try:
        html = _list_html(client, email)
        href = f'/admin/users/{user.id}'
        assert not re.search(rf'<a href="{re.escape(href)}">\s*0\s*</a>', html)
    finally:
        db.session.delete(db.session.merge(user))
        db.session.commit()
