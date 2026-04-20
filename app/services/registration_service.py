"""Registration business logic service (Course+CourseInstance era).

Реєстрація прив'язана до CourseInstance. `event_id` на таблиці
event_registrations зберігається як nullable artifact для legacy-рядків,
але не використовується новим кодом.
"""
import logging

from sqlalchemy import func

from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration

logger = logging.getLogger(__name__)


def find_existing(user_id, instance_id):
    """Знайти існуючу реєстрацію user+instance, або None."""
    return EventRegistration.query.filter_by(
        user_id=user_id, instance_id=instance_id,
    ).first()


def check_capacity(instance_id):
    """Перевірити наявність місць на instance з row-lock.

    Повертає (has_capacity: bool, locked_instance: CourseInstance | None).
    Caller повинен зробити commit або rollback.
    """
    locked_instance = (
        db.session.query(CourseInstance)
        .with_for_update()
        .filter_by(id=instance_id)
        .first()
    )
    if not locked_instance:
        return False, None

    cap = locked_instance.effective_max_participants
    if not cap:
        return True, locked_instance

    active_count = (
        db.session.query(func.count(EventRegistration.id))
        .filter(
            EventRegistration.instance_id == instance_id,
            EventRegistration.status.notin_(['cancelled']),
        )
        .scalar()
    )
    return active_count < cap, locked_instance


def create_or_reactivate(user_id, instance, form_data, existing=None):
    """Створити або переактивувати реєстрацію на CourseInstance.

    Args:
        user_id: Current user ID.
        instance: CourseInstance model instance.
        form_data: Dict (phone, specialty, workplace, experience_years, license_number).
        existing: Існуюча cancelled-реєстрація для реактивації, або None.

    Returns:
        (registration, is_free) tuple.
    """
    price = instance.effective_price or 0
    is_free = price == 0
    new_status = 'confirmed' if is_free else 'pending'
    new_payment = 'paid' if is_free else 'unpaid'

    if existing and existing.status == 'cancelled':
        existing.phone = form_data['phone']
        existing.specialty = form_data['specialty']
        existing.workplace = form_data['workplace']
        existing.experience_years = form_data.get('experience_years')
        existing.license_number = form_data.get('license_number')
        existing.payment_amount = price
        existing.status = new_status
        existing.payment_status = new_payment
        existing.payment_id = None
        existing.paid_at = None
        reg = existing
    else:
        reg = EventRegistration(
            user_id=user_id,
            instance_id=instance.id,
            phone=form_data['phone'],
            specialty=form_data['specialty'],
            workplace=form_data['workplace'],
            experience_years=form_data.get('experience_years'),
            license_number=form_data.get('license_number'),
            payment_amount=price,
            status=new_status,
            payment_status=new_payment,
        )
        db.session.add(reg)

    db.session.commit()
    return reg, is_free
