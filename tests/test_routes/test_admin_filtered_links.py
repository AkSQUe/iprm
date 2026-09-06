"""Числа й назви ведуть у відфільтрований перелік.

Три випадки: захід у картці контакту, лічильник вживань локації в довіднику
міст (шукає по `CourseInstance.location`) і лічильник запитів на курс (лише
"нових", тож посилання мусить нести і `course_id`, і `status='pending'` --
інакше воно веде на перелік, що містить і оброблені заявки, і число на
сторінці більше не відповідає тому, що покаже перехід). Кожен тест
перевіряє тег навколо значення, а не саму наявність URL на сторінці --
інакше пройшов би й на неклікабельному тексті.
"""
from tests.support.rbac import grant_role
import re
from urllib.parse import quote_plus
from uuid import uuid4

import pytest
from flask import url_for

from app.extensions import db
from app.models.city import City
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_request import CourseRequest
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'fl-{_uid()}@test.com', 'password123',
        first_name='F', last_name='L', email_confirmed=True,
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


def test_user_detail_target_title_links_to_instance_registrations(client, admin):
    """Захід у картці контакту веде у перелік зареєстрованих цього проведення."""
    user = User.create_with_password(
        f'fl-{_uid()}@test.com', 'password123',
        first_name='Тест', last_name='Учасник', email_confirmed=True,
    )
    db.session.flush()
    course = Course(title=f'Курс {_uid()}', slug=f'fl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380671110006',
        specialty='T', workplace='Клініка', status='confirmed', payment_status='paid',
    )
    db.session.add(reg)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/users/{user.id}').get_data(as_text=True)
        href = f'/admin/instances/{inst.id}/registrations'
        assert re.search(rf'<a href="{re.escape(href)}">\s*{re.escape(course.title)}', html)
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(user))
        db.session.commit()


def test_city_uses_count_links_to_filtered_schedule(client, admin):
    city_name = f'Тестове {_uid()}'
    city = City(name=city_name)
    db.session.add(city)
    db.session.flush()
    course = Course(title=f'Курс {_uid()}', slug=f'fl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published',
                          event_format='offline', location=city_name)
    db.session.add(inst)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/cities?q={quote_plus(city_name)}').get_data(as_text=True)
        href = f'/admin/instances?q={quote_plus(city_name)}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*1\s*</a>', html)
    finally:
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(city))
        db.session.commit()


def test_city_without_uses_stays_plain_text(client, admin):
    """Прочерк (0 вживань) не клікається."""
    city_name = f'Порожнє {_uid()}'
    city = City(name=city_name)
    db.session.add(city)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/cities?q={quote_plus(city_name)}').get_data(as_text=True)
        href = f'/admin/instances?q={quote_plus(city_name)}'
        assert not re.search(rf'<a href="{re.escape(href)}"', html)
    finally:
        db.session.delete(db.session.merge(city))
        db.session.commit()


def test_course_requests_summary_count_links_to_filtered_list(client, admin, app):
    """Зведення рахує лише 'нові' заявки -- посилання мусить нести і
    `course_id`, і `status='pending'`, інакше воно веде на перелік з іншим
    числом рядків, ніж те, що стоїть у клітинці. Href будуємо через
    `url_for`, а не рядком вручну: порядок параметрів у query string --
    деталь реалізації Werkzeug, а не контракт."""
    course = Course(title=f'Курс {_uid()}', slug=f'fl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    req = CourseRequest(
        course_id=course.id, email=f'fl-{_uid()}@test.com', status='pending',
    )
    db.session.add(req)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get('/admin/course-requests').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.course_requests_list',
                           course_id=course.id, status='pending')
        # Jinja екранує '&' у href в '&amp;' -- порівнюємо з тим, що
        # реально потрапляє в HTML, а не з сирим виводом url_for.
        href_in_html = href.replace('&', '&amp;')
        assert re.search(rf'<a href="{re.escape(href_in_html)}">\s*1\s*</a>', html)
    finally:
        db.session.delete(db.session.merge(req))
        db.session.delete(db.session.merge(course))
        db.session.commit()
