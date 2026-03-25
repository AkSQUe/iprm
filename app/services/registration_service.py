"""Registration business logic service.

Handles: duplicate checks, capacity validation with row locking,
registration creation and re-activation from cancelled state.
"""
import logging

from sqlalchemy import func

from app.extensions import db
from app.models.event import Event
from app.models.registration import EventRegistration

logger = logging.getLogger(__name__)


def find_existing(user_id, event_id):
    """Return existing registration for user+event, or None."""
    return EventRegistration.query.filter_by(
        user_id=user_id, event_id=event_id,
    ).first()


def check_capacity(event_id):
    """Check if event has available capacity using row-level lock.

    Returns (has_capacity: bool, locked_event: Event).
    Caller must commit or rollback the transaction.
    """
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


def create_or_reactivate(user_id, event, form_data, existing=None):
    """Create a new registration or reactivate a cancelled one.

    Args:
        user_id: Current user ID.
        event: Event model instance.
        form_data: Dict with phone, specialty, workplace, experience_years, license_number.
        existing: Existing cancelled registration to reactivate, or None.

    Returns:
        (registration, is_free) tuple.
    """
    is_free = not event.price or event.price == 0
    new_status = 'confirmed' if is_free else 'pending'
    new_payment = 'paid' if is_free else 'unpaid'

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
        reg = existing
    else:
        reg = EventRegistration(
            user_id=user_id,
            event_id=event.id,
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
