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


def _make_reservation(status, ref_suffix):
    # `instance_id` оголошено nullable=False, тож захід має бути справжнім
    # (той самий патерн, що й у tests/test_models/test_material_reservation_cost.py).
    # Слаг і external_ref прив'язані до `ref_suffix`: тестова БД тут не
    # відкочується між тестами (лише скидається наприкінці сесії), тож два
    # виклики цієї фікстури з однаковим слагом впали б на UNIQUE constraint.
    course = Course(title='Плазмотерапія', slug=f'course-reconcile-cost-{ref_suffix}')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, location='Київ')
    db.session.add(inst)
    db.session.flush()
    res = MaterialReservation(instance_id=inst.id,
                              external_ref=f'iprm-instance-reconcile-{ref_suffix}',
                              status=status)
    db.session.add(res)
    db.session.flush()
    res.items.append(MaterialReservationItem(sku='NDL-21', quantity_reserved=10,
                                             quantity_issued=10))
    db.session.commit()
    return res


@pytest.fixture
def reservation(app, request):
    return _make_reservation(MaterialReservationStatus.ISSUED, request.node.name)


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


def test_reconcile_advances_status_and_applies_items_together(app, request, monkeypatch):
    """Загублений термінальний штовх: локально ще ISSUED, знімок партнера -- consumed.

    MM Medic шле такий рядок LEGACY-форматом (без `quantity_approved`): коли
    рядків документа більше немає, `quantity` -- це спожита кількість, а не
    погоджена. Регресія, яку цей тест ловить: якби рядки розбирались під
    ПОТОЧНИМ (ISSUED, нетермінальним) статусом замість того, що НАБУДЕ
    чинності (CONSUMED), гілка "quantity -- це погоджене" спрацювала б і
    затерла `quantity_reserved` спожитою цифрою -- саме те, від чого
    застерігає докстрінг `apply_items`.
    """
    res = _make_reservation(MaterialReservationStatus.ISSUED, request.node.name)

    class _Client:
        def get_reservation(self, ref):
            return _FakeResult({'reservation': {
                'status': 'consumed',
                'items': [{'sku': 'NDL-21', 'quantity': 7}],
            }})

    monkeypatch.setattr(mrs, 'get_client', lambda: _Client())

    assert mrs.reconcile_reservation(res) is True

    fresh = MaterialReservation.query.get(res.id)
    assert fresh.status == MaterialReservationStatus.CONSUMED
    item = fresh.items[0]
    assert item.quantity_reserved == 10  # НЕ 7 -- захищене цим тестом


def test_reconcile_applies_items_when_may_advance_rejects_status(app, request, monkeypatch):
    """`_may_advance` відхиляє знімок партнера, але рядки все одно читаються.

    Раніше функція виходила рівно тут (`return False`), щойно перехід
    визнано неприпустимим -- рядки взагалі не розбирались. Тепер відхилений
    `new_status` не заважає прочитати рядки під статусом, що ЛИШАЄТЬСЯ
    чинним.
    """
    res = _make_reservation(MaterialReservationStatus.RESERVED, request.node.name)

    class _Client:
        def get_reservation(self, ref):
            return _FakeResult({'reservation': {
                # 'submitted' -- відкат назад відносно RESERVED, _may_advance
                # такий перехід відхилить.
                'status': 'submitted',
                'items': [{'sku': 'NDL-21', 'cost_uah': '42.00', 'cost_complete': True}],
            }})

    monkeypatch.setattr(mrs, 'get_client', lambda: _Client())

    assert mrs.reconcile_reservation(res) is True

    fresh = MaterialReservation.query.get(res.id)
    assert fresh.status == MaterialReservationStatus.RESERVED
    assert fresh.items[0].cost_uah == Decimal('42.00')


def test_reconcile_returns_false_when_nothing_changed(app, reservation, monkeypatch):
    """Ні статус, ні рядки не змінились -- жодного commit, повертає False."""
    class _Client:
        def get_reservation(self, ref):
            return _FakeResult({'reservation': {'status': 'issued'}})

    monkeypatch.setattr(mrs, 'get_client', lambda: _Client())
    last_response_before = reservation.last_response

    assert mrs.reconcile_reservation(reservation) is False

    fresh = MaterialReservation.query.get(reservation.id)
    assert fresh.status == MaterialReservationStatus.ISSUED
    assert fresh.last_response == last_response_before
