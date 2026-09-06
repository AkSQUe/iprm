"""Колонка «Місця» в розкладі адмінки: зайнято/місткість і перевищення.

Місце тримає лише оплачена реєстрація (app/services/seating.py), а
перевищення пулу (оплата прийшла після заповнення) має бути видно
червоною плашкою -- інакше менеджер дізнається про нього в залі.
"""
from tests.support.rbac import grant_role
import re
from datetime import datetime, timedelta, timezone
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
        f'seats-{_uid()}@test.com', 'password123',
        first_name='S', last_name='A', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


@pytest.fixture
def instance(app, admin):
    created = []
    course = Course(title=f'Місткість {_uid()}', slug=f'seats-{_uid()}',
                    is_active=True, max_participants=2)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
        max_participants=2,
    )
    db.session.add(inst)
    db.session.flush()
    created += [inst, course]
    db.session.commit()
    yield inst
    db.session.rollback()
    EventRegistration.query.filter_by(instance_id=inst.id).delete()
    for obj in created:
        db.session.delete(db.session.merge(obj))
    db.session.commit()


def _list_html(client, instance):
    """Список, звужений до курсу тесту.

    Сесія тестів ділить одну БД, тож "1/2" з чужого рядка робив би
    перевірки випадковими.
    """
    url = f'/admin/instances?course_id={instance.course_id}'
    return client.get(url).get_data(as_text=True)


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _add_reg(instance, status, payment_status):
    user = User.create_with_password(
        f'p-{_uid()}@test.com', 'password123', first_name='P', last_name='X',
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380671110002',
        specialty='T', workplace='Клініка',
        status=status, payment_status=payment_status,
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def test_unpaid_registration_does_not_take_seat(client, admin, instance):
    _add_reg(instance, 'pending', 'unpaid')
    _login(client, admin)

    html = _list_html(client, instance)
    assert '0/2' in html
    assert 'admin-seats--over' not in html


def test_paid_registration_takes_seat(client, admin, instance):
    _add_reg(instance, 'confirmed', 'paid')
    _add_reg(instance, 'pending', 'unpaid')
    _login(client, admin)

    html = _list_html(client, instance)
    assert '1/2' in html


def test_overbooking_is_marked_red(client, admin, instance):
    for _ in range(3):
        _add_reg(instance, 'confirmed', 'paid')
    _login(client, admin)

    html = _list_html(client, instance)
    assert '3/2' in html
    assert 'admin-seats--over' in html


def test_course_title_links_to_registrations(client, admin, instance):
    _login(client, admin)

    html = _list_html(client, instance)
    assert f'/admin/instances/{instance.id}/registrations' in html


def test_registration_count_links_to_registrations(client, admin, instance):
    """Число в колонці «Реєстрацій» -- вхід у перелік зареєстрованих.

    Курс у сусідній колонці веде туди ж, тож перевіряємо саме тег навколо
    числа: інакше тест пройшов би й на неклікабельній цифрі.
    """
    reg = _add_reg(instance, 'pending', 'unpaid')
    user_id = reg.user_id
    _login(client, admin)
    try:
        html = _list_html(client, instance)
        href = f'/admin/instances/{instance.id}/registrations'
        assert re.search(rf'<a href="{re.escape(href)}">\s*1\s*</a>', html)
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.commit()
        db.session.delete(db.session.get(User, user_id))
        db.session.commit()


def test_zero_registrations_stays_plain_text(client, admin, instance):
    """Нуль не клікається -- розгортати там нічого."""
    _login(client, admin)

    html = _list_html(client, instance)
    href = f'/admin/instances/{instance.id}/registrations'
    assert not re.search(rf'<a href="{re.escape(href)}">\s*0\s*</a>', html)


def test_next3_skips_drafts(client, admin, instance):
    """Чернетка не займає слот у трійці найближчих, хоч і ближча за датою.

    Позитивну частину ("опубліковане на місці") не перевіряємо через HTTP:
    сесія тестів ділить одну БД, і трійку можуть зайняти чужі заходи з
    ближчими датами. Гарантія тут -- саме відсутність чернетки.
    """
    draft = CourseInstance(
        course_id=instance.course_id, status='draft', event_format='offline',
        start_date=instance.start_date - timedelta(days=1),
    )
    db.session.add(draft)
    db.session.commit()
    _login(client, admin)
    try:
        next3 = client.get('/admin/instances?quick=next3').get_data(as_text=True)
        assert f'/admin/instances/{draft.id}/registrations' not in next3
        # ...і при цьому чернетка нікуди не зникла зі списку взагалі.
        drafts = client.get('/admin/instances?status=draft').get_data(as_text=True)
        assert f'/admin/instances/{draft.id}/registrations' in drafts
    finally:
        db.session.delete(db.session.merge(draft))
        db.session.commit()
