"""Місткість заходу: місце тримає лише ОПЛАЧЕНА реєстрація.

Рішення 12.08.2026. До нього зайнятим вважалось будь-яке не-скасоване
записування, тож двоє тестових `pending`/`unpaid` закрили продаж заходу,
де фізично були вільні місця, і зняти їх можна було тільки вручну.

Наслідок нового правила: оплата може прийти вже після того, як пул
розібрали інші платники (людина висіла в pending, поки місця скінчились,
і оплатила пізніше). Гроші не відхиляємо -- фіксуємо перевищення: список
проведень показує його червоним (7/6), а адміну йде лист.

Єдине джерело правди для всіх, хто рахує місця: публічні лістинги
(course_listing), гейт реєстрації (registration_service), адмінка,
партнерське API і xlsx-звіти.
"""
import logging

from app.extensions import db
from app.models.registration import EventRegistration

logger = logging.getLogger(__name__)


def occupied_clause():
    """SQL-умова "ця реєстрація тримає місце".

    Скасовані не рахуються навіть якщо колись були оплачені (refunded
    приходить у парі зі status='cancelled'), решта -- рівно за фактом
    оплати.
    """
    return db.and_(
        EventRegistration.status != 'cancelled',
        EventRegistration.payment_status == 'paid',
    )


def occupied_counts(instance_ids):
    """{instance_id: зайнятих місць} одним запитом (без N+1)."""
    ids = list(instance_ids)
    if not ids:
        return {}
    rows = (
        db.session.query(
            EventRegistration.instance_id,
            db.func.count(EventRegistration.id),
        )
        .filter(EventRegistration.instance_id.in_(ids), occupied_clause())
        .group_by(EventRegistration.instance_id)
        .all()
    )
    counts = dict(rows)
    return {inst_id: counts.get(inst_id, 0) for inst_id in ids}


def occupied_count(instance_id):
    """Зайнятих місць на одному проведенні."""
    return (
        db.session.query(db.func.count(EventRegistration.id))
        .filter(EventRegistration.instance_id == instance_id, occupied_clause())
        .scalar()
    ) or 0


def seats_left(capacity, occupied):
    """Вільні місця; None -- місткість не задана (необмежено).

    Ніколи не від'ємне: перевищення показуємо окремо (occupied/capacity),
    а "мінус два місця" у картці курсу нічого не пояснює покупцю.
    """
    if capacity is None:
        return None
    return max(capacity - occupied, 0)


def is_overbooked(capacity, occupied):
    return capacity is not None and occupied > capacity


def notify_overbooking_if_needed(reg):
    """Після оплати: якщо оплачених стало більше за місткість -- лист адміну.

    Best-effort і повністю ізольовано: жоден збій тут не має чіпати саму
    оплату (гроші вже списані, реєстрація вже підтверджена).

    Повертає True, якщо лист поставлено в чергу.
    """
    try:
        instance = reg.instance
        if instance is None:
            return False
        capacity = instance.effective_max_participants
        occupied = occupied_count(reg.instance_id)
        if not is_overbooked(capacity, occupied):
            return False

        logger.warning(
            'Overbooking on instance %d: %d paid seats of %d capacity (REG-%d)',
            instance.id, occupied, capacity, reg.id,
        )
        from app.services.email_service import EmailService
        EmailService.notify_overbooking(reg, occupied=occupied, capacity=capacity)
        return True
    except Exception:
        logger.exception(
            'Overbooking check failed for REG-%s', getattr(reg, 'id', '?'),
        )
        return False
