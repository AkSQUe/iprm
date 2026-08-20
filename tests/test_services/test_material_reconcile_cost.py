"""Звірка мусить забирати з MM Medic не лише статус, а й рядки.

Штовхач на боці партнера -- демон-потік без ретраїв, тож загублена доставка
це нормальний, а не винятковий випадок. Єдине, що її виправляє, -- ця звірка.
Доти вона виходила раніше, щойно статус не змінився, і собівартість, яка
приїхала б у відповіді GET, просто не читалась.
"""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem, MaterialReservationStatus,
)
from app.services import material_reservation_service as mrs


class _FakeResult:
    ok = True

    def __init__(self, data):
        self.data = data


@pytest.fixture
def reservation(app, request):
    # `instance_id` оголошено nullable=False, тож захід має бути справжнім
    # (той самий патерн, що й у tests/test_models/test_material_reservation_cost.py).
    # Слаг і external_ref прив'язані до імені тесту: тестова БД тут не
    # відкочується між тестами (лише скидається наприкінці сесії), тож два
    # виклики цієї фікстури з однаковим слагом впали б на UNIQUE constraint.
    suffix = request.node.name
    course = Course(title='Плазмотерапія', slug=f'course-reconcile-cost-{suffix}')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, location='Київ')
    db.session.add(inst)
    db.session.flush()
    res = MaterialReservation(instance_id=inst.id,
                              external_ref=f'iprm-instance-reconcile-{suffix}',
                              status=MaterialReservationStatus.ISSUED)
    db.session.add(res)
    db.session.flush()
    res.items.append(MaterialReservationItem(sku='NDL-21', quantity_reserved=10,
                                             quantity_issued=10))
    db.session.commit()
    return res


def test_reconcile_applies_cost_even_when_status_unchanged(app, reservation, monkeypatch):
    class _Client:
        def get_reservation(self, ref):
            return _FakeResult({'reservation': {
                'status': 'issued',
                'items': [{'sku': 'NDL-21', 'quantity_issued': 10,
                           'quantity_returned': 2,
                           'cost_uah': '99.50', 'cost_complete': True}],
            }})

    monkeypatch.setattr(mrs, 'get_client', lambda: _Client())

    mrs.reconcile_reservation(reservation)

    item = MaterialReservation.query.get(reservation.id).items[0]
    assert item.cost_uah == Decimal('99.50')
    assert item.cost_complete is True
    assert item.quantity_returned == 2


def test_reconcile_leaves_status_alone_when_partner_agrees(app, reservation, monkeypatch):
    """Читання рядків не має права рухати статус: це різні питання."""
    class _Client:
        def get_reservation(self, ref):
            return _FakeResult({'reservation': {
                'status': 'issued',
                'items': [{'sku': 'NDL-21', 'cost_uah': '10.00', 'cost_complete': True}],
            }})

    monkeypatch.setattr(mrs, 'get_client', lambda: _Client())

    mrs.reconcile_reservation(reservation)

    assert MaterialReservation.query.get(reservation.id).status == (
        MaterialReservationStatus.ISSUED)
