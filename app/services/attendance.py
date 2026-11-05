"""Відмітка участі (був / не з'явився / не відмічено) без наслідків для грошей.

Відмітка лише описує факт про людину: статус, бали БПР, сертифікат і оплату
вона не чіпає. Масова дія ставить «Не з'явився» тим, кого після заходу так і
не відмітили; масовий UPDATE не викликає ORM-слухачів `partner_events`, і це
бажано: партнер розуміє лише подію «був присутній».
"""
import logging

from app.extensions import db
from app.models.registration import EventRegistration
from app.services.bpr_report import event_has_ended

audit_logger = logging.getLogger('audit')


class AttendanceError(ValueError):
    """Масову відмітку відхилено (захід ще не закінчився)."""


def mark_unmarked_absent(instance, by_user) -> int:
    """Поставити «Не з'явився» нескасованим реєстраціям без відмітки.

    Повертає кількість позначених. Захід, що ще не закінчився, -- AttendanceError.
    Комітить сам.
    """
    if not event_has_ended(instance):
        raise AttendanceError('Захід ще не закінчився')

    marked = EventRegistration.query.filter(
        EventRegistration.instance_id == instance.id,
        EventRegistration.status != 'cancelled',
        EventRegistration.attended.is_(None),
    ).update({'attended': False}, synchronize_session='fetch')
    db.session.commit()
    audit_logger.info(
        'Admin %s marked %d unmarked registrations of instance %d as absent',
        getattr(by_user, 'email', None) or str(by_user), marked, instance.id,
    )
    return marked
