"""Подана заявка нічого не резервує -- і дзеркало не має стверджувати інше.

MM Medic шле `quantity` завжди, а для поданого документа воно дорівнює
ЗАПИТАНОМУ: legacy-поле заповнюється `quantity_requested`, поки погодженого
немає. Доки легасі-відкат спрацьовував на будь-якому непідсумковому статусі,
це число лягало в `quantity_reserved` -- і ІПРМ показував резерв, якого не
існує: у колонці «Зарезервовано» на сторінці тренера (саме те число, яке ми
просимо його підтвердити), у пікінг-листі, у підсумках зведення і в
xlsx-експорті.

Відкат писався під payload-и форми утримань, тож і дійсний лише там, де
утримання є, -- від RESERVED і вище.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem, MaterialReservationStatus,
)
from app.services import material_reservation_service as mrs


class _Result:
    ok = True
    error = None
    shortfalls = ()

    def __init__(self, data=None):
        self.data = data or {}


def _instance():
    suffix = uuid4().hex[:8]
    course = Course(title='Плазмотерапія', slug=f'sub-{suffix}')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(course_id=course.id, location='Київ')
    db.session.add(instance)
    db.session.flush()
    return instance


def _reservation(instance, status):
    reservation = MaterialReservation(
        instance_id=instance.id,
        external_ref=f'iprm-instance-{instance.id}',
        status=status)
    db.session.add(reservation)
    db.session.flush()
    return reservation


@pytest.fixture
def reservation(app):
    return _reservation(_instance(), MaterialReservationStatus.SUBMITTED)


def _submitted_line(quantity=7):
    """Рівно те, що шле MM Medic на подання: legacy-`quantity` дорівнює
    запитаному, погодженого ще немає."""
    return {'sku': 'NDL-21', 'name': 'Голка 21G', 'quantity': quantity,
            'quantity_requested': quantity, 'quantity_approved': None,
            'quantity_issued': None, 'quantity_returned': None}


class TestSubmittedPushReportsNoReserve:
    def test_requested_quantity_does_not_become_a_reserve(self, app, reservation):
        mrs.apply_items(reservation, [_submitted_line(7)],
                        MaterialReservationStatus.SUBMITTED, True)

        item = reservation.items[0]
        assert item.quantity_requested == 7
        assert item.quantity_reserved == 0, 'дзеркало показує резерв, якого немає'

    def test_a_previous_approval_does_not_survive_a_resubmit(self, app, reservation):
        """Друге коло після відмови: стара погоджена кількість не має
        лишатись висіти як діючий резерв."""
        reservation.items.append(MaterialReservationItem(
            sku='NDL-21', name='Голка 21G', quantity_requested=7,
            quantity_reserved=5))
        db.session.flush()

        mrs.apply_items(reservation, [_submitted_line(9)],
                        MaterialReservationStatus.SUBMITTED, True)

        item = reservation.items[0]
        assert item.quantity_requested == 9
        assert item.quantity_reserved == 0

    def test_submit_request_leaves_the_mirror_without_a_reserve(self, app,
                                                                monkeypatch):
        """Наскрізно: відповідь на подання будує рядки дзеркала, і в них не
        має бути резерву."""
        instance = _instance()

        class _Client:
            def submit_request(self, ref, meta, items, request_id=None):
                return _Result({'status': 'created', 'reservation': {
                    'status': 'submitted', 'items': [_submitted_line(6)],
                }})

        monkeypatch.setattr(mrs, 'get_client', lambda: _Client())

        ok, _result, reservation = mrs.submit_request(
            instance, [{'sku': 'NDL-21', 'quantity': 6}])

        assert ok is True
        assert reservation.status == MaterialReservationStatus.SUBMITTED
        assert reservation.items[0].quantity_requested == 6
        assert reservation.items[0].quantity_reserved == 0


class TestApprovedPushStillCarriesTheReserve:
    def test_legacy_quantity_is_still_read_as_approved(self, app):
        """Старий канал шле лише `quantity`, і там воно означає погоджене.
        Звузити відкат не означає його прибрати."""
        reservation = _reservation(_instance(), MaterialReservationStatus.SUBMITTED)

        mrs.apply_items(reservation, [{'sku': 'NDL-21', 'quantity': 5}],
                        MaterialReservationStatus.RESERVED, True)

        assert reservation.items[0].quantity_reserved == 5

    def test_explicit_approval_wins_at_any_status(self, app, reservation):
        mrs.apply_items(
            reservation,
            [{'sku': 'NDL-21', 'quantity': 7, 'quantity_requested': 7,
              'quantity_approved': 4}],
            MaterialReservationStatus.RESERVED, True)

        assert reservation.items[0].quantity_reserved == 4
