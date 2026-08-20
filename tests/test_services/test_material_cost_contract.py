"""Контракт рядка: імена й одиниці, про які домовились два репозиторії.

Цей тест не перевіряє логіку -- її перевіряють сусідні файли. Він фіксує
СЛОВНИК: перейменування `cost_uah` у MM Medic не має шансу тихо доїхати
сюди, бо мовчазна відсутність поля тут виглядала б як «партнер ще не
оновився», і собівартість просто лишалась би порожньою місяцями.

Еталонний payload узятий із `_serialize_item` MM Medic станом на 20.08.2026.
"""
from decimal import Decimal

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem, MaterialReservationStatus,
)
from app.services import material_reservation_service as mrs

#: Рівно те, що віддає MM Medic на рядок документа.
PARTNER_ITEM_PAYLOAD = {
    'sku': 'NDL-21',
    'name': 'Голка 21G',
    'image': None,
    'quantity': 8,
    'quantity_requested': 12,
    'quantity_approved': 11,
    'quantity_issued': 10,
    'quantity_returned': 2,
    # Рядок, а не число: Flask серіалізує Decimal через str, і для грошей це
    # правильно -- float після кількох додавань дає копійки нізвідки.
    'cost_uah': '80.00',
    'cost_complete': True,
}


def test_partner_item_payload_lands_whole(app):
    # `instance_id` оголошено nullable=False, тож захід має бути справжнім.
    course = Course(title='Плазмотерапія', slug='course-cost-contract')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, location='Київ')
    db.session.add(inst)
    db.session.flush()
    res = MaterialReservation(instance_id=inst.id, external_ref='iprm-instance-8001',
                              status=MaterialReservationStatus.ISSUED)
    db.session.add(res)
    db.session.flush()
    res.items.append(MaterialReservationItem(sku='NDL-21', quantity_reserved=11))
    db.session.commit()

    mrs.apply_items(res, [PARTNER_ITEM_PAYLOAD],
                    MaterialReservationStatus.ISSUED, True)
    db.session.commit()

    item = db.session.get(MaterialReservation, res.id).items[0]
    assert item.quantity_requested == 12
    assert item.quantity_reserved == 11
    assert item.quantity_issued == 10
    assert item.quantity_returned == 2
    assert item.quantity_actual == 8
    assert item.cost_uah == Decimal('80.00')
    assert item.cost_complete is True
