"""Що сторінка матеріалів ІПРМ має право робити з документом MM Medic.

Заявка переїхала на новий канал: ІПРМ подає ДОКУМЕНТ, комірник погоджує й
видає, і саме видача вішає на рядки партії, з яких береться собівартість
заходу. Легасі-дії сторінки (списання, коригування) написані під старий
канал -- утримання без рядків. Застосовані до документа, вони закривають
його не створивши жодної партії: `issue()` після цього неможливий, а
собівартість недосяжна назавжди.

Тому сторінка їх не пропонує, а маршрути відмовляють. MM Medic відмовляє й
на своєму боці (`actuals_unsupported_for_document`) -- тут перевіряється
наш бік.
"""
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
        f'md-admin-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='А', last_name='Адмін', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _instance():
    suffix = uuid4().hex[:8]
    course = Course(title='Плазмотерапія', slug=f'md-{suffix}')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(course_id=course.id, location='Київ')
    db.session.add(instance)
    db.session.flush()
    return instance


def _reservation(instance, status, *, requested=None, reserved=0):
    reservation = MaterialReservation(
        instance_id=instance.id,
        external_ref=f'iprm-instance-{instance.id}',
        status=status,
    )
    db.session.add(reservation)
    db.session.flush()
    reservation.items.append(MaterialReservationItem(
        sku='NDL-21', name='Голка 21G',
        quantity_requested=requested, quantity_reserved=reserved))
    db.session.flush()
    return reservation


class TestIsMmDocument:
    def test_a_legacy_hold_is_not_a_document(self, app):
        instance = _instance()
        reservation = _reservation(instance, MaterialReservationStatus.RESERVED,
                                   requested=None, reserved=5)

        assert reservation.is_mm_document is False

    def test_requested_quantity_marks_a_document(self, app):
        instance = _instance()
        reservation = _reservation(instance, MaterialReservationStatus.RESERVED,
                                   requested=7, reserved=7)

        assert reservation.is_mm_document is True

    def test_submitted_is_a_document_even_without_rows(self, app):
        """Штовх статусу летить без ретраїв: рядки можуть відстати, а
        SUBMITTED легасі-канал не виробляє взагалі."""
        instance = _instance()
        reservation = MaterialReservation(
            instance_id=instance.id,
            external_ref=f'iprm-instance-{instance.id}',
            status=MaterialReservationStatus.SUBMITTED)
        db.session.add(reservation)
        db.session.flush()

        assert reservation.is_mm_document is True


class TestWriteOffIsRefusedForADocument:
    def test_actuals_route_refuses_and_calls_nobody(self, app, client, admin,
                                                    monkeypatch):
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.RESERVED,
                     requested=7, reserved=7)
        _login(client, admin)

        def _explode(*a, **kw):
            raise AssertionError('легасі-списання пішло в MM Medic')

        monkeypatch.setattr(routes.mrs, 'submit_actuals', _explode)

        response = client.post(
            f'/admin/instances/{instance.id}/materials/actuals',
            data={'sku': 'NDL-21', 'actual': '7'}, follow_redirects=True)

        assert response.status_code == 200
        assert 'керує документ MM Medic' in response.get_data(as_text=True)

    def test_adjust_route_refuses(self, app, client, admin, monkeypatch):
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.CONSUMED,
                     requested=7, reserved=7)
        _login(client, admin)

        def _explode(*a, **kw):
            raise AssertionError('легасі-коригування пішло в MM Medic')

        monkeypatch.setattr(routes.mrs, 'adjust_actuals', _explode)

        response = client.post(
            f'/admin/instances/{instance.id}/materials/adjust',
            data={'sku': 'NDL-21', 'actual': '5'}, follow_redirects=True)

        assert 'керує документ MM Medic' in response.get_data(as_text=True)

    def test_a_legacy_reservation_still_writes_off(self, app, client, admin,
                                                   monkeypatch):
        """Старий канал не має постраждати: у проді він живий."""
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.RESERVED,
                     requested=None, reserved=5)
        _login(client, admin)
        called = {}

        def _fake(instance_arg, actuals, **kw):
            called['actuals'] = actuals
            return True, type('R', (), {'ok': True, 'data': {}, 'error': None})()

        monkeypatch.setattr(routes.mrs, 'submit_actuals', _fake)

        client.post(f'/admin/instances/{instance.id}/materials/actuals',
                    data={'sku': 'NDL-21', 'actual': '4'}, follow_redirects=True)

        assert called['actuals'] == [{'sku': 'NDL-21', 'actual_qty': 4}]

    def test_the_page_offers_no_write_off_button(self, app, client, admin):
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.RESERVED,
                     requested=7, reserved=7)
        _login(client, admin)

        html = client.get(
            f'/admin/instances/{instance.id}/materials').get_data(as_text=True)

        assert 'Провести списання' not in html
        assert 'Списання виконує комірник' in html
