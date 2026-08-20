"""Підтвердження тренера має бути ВИДНО там, куди дивиться івент-менеджер.

Тренер відкриває підписане посилання, бачить перелік і пише «ще треба
голок» -- і чує «Дякуємо, ваше підтвердження отримано». Доки `trainer_comment`
і `trainer_confirmed_at` не читались у жодному шаблоні, списку чи експорті,
це була активна обіцянка зовнішньому користувачеві, якої система не
виконувала: коментар нікуди не потрапляв.

Читаються вони саме на двох екранах, де менеджер уже буває: картка заходу
(`admin/materials.html`) і зведення `/admin/materials`. Окремого екрана під
це не заводимо -- сторінка, куди ніхто не ходить, нічого не змінює.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.admin import routes_materials as routes
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem, MaterialReservationStatus,
)
from app.models.user import User

COMMENT = 'Ще треба голок 21G, привезіть із запасом'

FAKE_CATALOG = [
    {'sku': 'NDL-21', 'name': 'Голка 21G', 'available': 100, 'price': 12.5,
     'category': 'Голки', 'is_consumable': True},
]


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    monkeypatch.setattr(routes.mrs, 'get_catalog',
                        lambda **kw: (FAKE_CATALOG, None, False))


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'tc-admin-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='А', last_name='Адмін', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


@pytest.fixture
def confirmed(app, admin):
    suffix = uuid4().hex[:8]
    course = Course(title='Плазмотерапія', slug=f'tc-{suffix}')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(course_id=course.id, location='Київ')
    db.session.add(instance)
    db.session.flush()
    reservation = MaterialReservation(
        instance_id=instance.id,
        external_ref=f'iprm-instance-{instance.id}',
        status=MaterialReservationStatus.RESERVED,
        created_by_id=admin.id,
        trainer_confirmed_at=datetime(2026, 8, 19, 14, 30, tzinfo=timezone.utc),
        trainer_comment=COMMENT,
    )
    db.session.add(reservation)
    db.session.flush()
    reservation.items.append(MaterialReservationItem(
        sku='NDL-21', name='Голка 21G', quantity_reserved=5))
    db.session.flush()
    return instance


class TestEventCard:
    def test_the_comment_is_on_the_page(self, app, client, admin, confirmed):
        _login(client, admin)

        html = client.get(
            f'/admin/instances/{confirmed.id}/materials').get_data(as_text=True)

        assert COMMENT in html

    def test_the_confirmation_time_is_on_the_page(self, app, client, admin,
                                                  confirmed):
        _login(client, admin)

        html = client.get(
            f'/admin/instances/{confirmed.id}/materials').get_data(as_text=True)

        assert 'тренер підтвердив' in html
        assert '19.08.2026' in html

    def test_who_filed_the_request_is_named(self, app, client, admin, confirmed):
        """`created_by_id` теж писався і теж ніде не читався."""
        _login(client, admin)

        html = client.get(
            f'/admin/instances/{confirmed.id}/materials').get_data(as_text=True)

        assert 'подав' in html
        assert 'Адмін А' in html

    def test_an_unconfirmed_reservation_says_so(self, app, client, admin,
                                                confirmed):
        reservation = MaterialReservation.query.filter_by(
            instance_id=confirmed.id).one()
        reservation.trainer_confirmed_at = None
        reservation.trainer_comment = None
        db.session.flush()
        _login(client, admin)

        html = client.get(
            f'/admin/instances/{confirmed.id}/materials').get_data(as_text=True)

        assert 'Тренер ще не підтвердив' in html


class TestOverview:
    def test_the_comment_reaches_the_list(self, app, client, admin, confirmed):
        _login(client, admin)

        html = client.get('/admin/materials').get_data(as_text=True)

        assert COMMENT in html
        assert '19.08.2026' in html
