"""Собівартість рядка резервування: три різні стани, а не два.

NULL -- «оцінити нічим» (партій ще немає або в жодної не було ціни).
Нуль -- «порахували, вийшло нуль». Плутати їх не можна: у звіті перше має
бути прочерком, друге -- нулем.
"""
from decimal import Decimal

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem,
)


def _reservation(ref, slug):
    """`instance_id` оголошено nullable=False, тож захід має бути справжнім."""
    course = Course(title='Плазмотерапія', slug=f'course-{slug}')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, location='Київ')
    db.session.add(inst)
    db.session.flush()
    res = MaterialReservation(instance_id=inst.id, external_ref=ref, status='issued')
    db.session.add(res)
    db.session.flush()
    return res


def test_cost_defaults_to_null(app):
    res = _reservation('iprm-instance-9001', 'c1')
    item = MaterialReservationItem(sku='NDL-21', quantity_reserved=5)
    res.items.append(item)
    db.session.flush()

    assert item.cost_uah is None
    assert item.cost_complete is None


def test_cost_stores_two_decimal_places(app):
    res = _reservation('iprm-instance-9002', 'c2')
    item = MaterialReservationItem(sku='NDL-21', quantity_reserved=5,
                                   cost_uah=Decimal('123.45'), cost_complete=True)
    res.items.append(item)
    db.session.flush()

    assert item.cost_uah == Decimal('123.45')
    assert item.cost_complete is True


def test_zero_cost_is_not_null(app):
    res = _reservation('iprm-instance-9003', 'c3')
    item = MaterialReservationItem(sku='NDL-21', quantity_reserved=5,
                                   cost_uah=Decimal('0.00'), cost_complete=True)
    res.items.append(item)
    db.session.flush()

    assert item.cost_uah is not None
    assert item.cost_uah == Decimal('0.00')
