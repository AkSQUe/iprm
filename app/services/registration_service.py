"""Registration business logic service.

Підтримує два шляхи:
  * Legacy: реєстрація на Event (стара модель) -- збереглося для сумісності URL
  * New: реєстрація на CourseInstance (нова модель)

Обидва створюють запис у event_registrations. Унікальність:
  uq_user_instance_registration -- один користувач не може зареєструватися двічі
  на той самий instance. Для legacy-реєстрацій без instance_id обмеження
  не діє (має враховуватися на рівні застосунку через find_existing_by_event).
"""
import logging

from sqlalchemy import func

from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.event import Event
from app.models.registration import EventRegistration

logger = logging.getLogger(__name__)


def find_existing_by_event(user_id, event_id):
    return EventRegistration.query.filter_by(
        user_id=user_id, event_id=event_id,
    ).first()


def find_existing_by_instance(user_id, instance_id):
    return EventRegistration.query.filter_by(
        user_id=user_id, instance_id=instance_id,
    ).first()


# Backward-compat alias
def find_existing(user_id, event_id):
    return find_existing_by_event(user_id, event_id)


def check_capacity_event(event_id):
    """Legacy шлях: capacity per Event."""
    locked_event = (
        db.session.query(Event)
        .with_for_update()
        .filter_by(id=event_id)
        .first()
    )
    if not locked_event:
        return False, None
    if not locked_event.max_participants:
        return True, locked_event

    active_count = (
        db.session.query(func.count(EventRegistration.id))
        .filter(
            EventRegistration.event_id == event_id,
            EventRegistration.status.notin_(['cancelled']),
        )
        .scalar()
    )
    return active_count < locked_event.max_participants, locked_event


def check_capacity_instance(instance_id):
    """New шлях: capacity per CourseInstance (з fallback на Course.max_participants)."""
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


# Backward-compat alias
def check_capacity(event_id):
    return check_capacity_event(event_id)


def create_or_reactivate_event(user_id, event, form_data, existing=None):
    """Legacy: реєстрація на Event. Зберігається як є -- але заповнюємо
    instance_id якщо існує Course+Instance з тим самим slug (1:1 mapping
    з Phase 2)."""
    is_free = not event.price or event.price == 0
    new_status = 'confirmed' if is_free else 'pending'
    new_payment = 'paid' if is_free else 'unpaid'

    # Шукаємо відповідний instance через Course.slug=Event.slug
    from app.models.course import Course
    course = Course.query.filter_by(slug=event.slug).first()
    linked_instance_id = None
    if course and course.instances:
        # Для legacy event -> беремо instance з найближчим start_date (найчастіше 1:1)
        instance = sorted(
            course.instances,
            key=lambda i: abs((i.start_date - event.start_date).total_seconds())
            if i.start_date and event.start_date else 0,
        )[0]
        linked_instance_id = instance.id

    if existing and existing.status == 'cancelled':
        existing.phone = form_data['phone']
        existing.specialty = form_data['specialty']
        existing.workplace = form_data['workplace']
        existing.experience_years = form_data.get('experience_years')
        existing.license_number = form_data.get('license_number')
        existing.payment_amount = event.price or 0
        existing.status = new_status
        existing.payment_status = new_payment
        existing.payment_id = None
        existing.paid_at = None
        if linked_instance_id and not existing.instance_id:
            existing.instance_id = linked_instance_id
        reg = existing
    else:
        reg = EventRegistration(
            user_id=user_id,
            event_id=event.id,
            instance_id=linked_instance_id,
            phone=form_data['phone'],
            specialty=form_data['specialty'],
            workplace=form_data['workplace'],
            experience_years=form_data.get('experience_years'),
            license_number=form_data.get('license_number'),
            payment_amount=event.price or 0,
            status=new_status,
            payment_status=new_payment,
        )
        db.session.add(reg)

    db.session.commit()
    return reg, is_free


def create_or_reactivate_instance(user_id, instance, form_data, existing=None):
    """New: реєстрація на CourseInstance. Заповнюємо також event_id якщо
    існує legacy Event з тим самим slug."""
    price = instance.effective_price or 0
    is_free = price == 0
    new_status = 'confirmed' if is_free else 'pending'
    new_payment = 'paid' if is_free else 'unpaid'

    # Шукаємо legacy Event (для поточних мігрованих даних)
    legacy_event = Event.query.filter_by(slug=instance.course.slug).first() if instance.course else None
    legacy_event_id = legacy_event.id if legacy_event else None

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
        if not existing.event_id and legacy_event_id:
            existing.event_id = legacy_event_id
        reg = existing
    else:
        reg = EventRegistration(
            user_id=user_id,
            instance_id=instance.id,
            event_id=legacy_event_id,
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


# Backward-compat alias
def create_or_reactivate(user_id, event, form_data, existing=None):
    return create_or_reactivate_event(user_id, event, form_data, existing)
