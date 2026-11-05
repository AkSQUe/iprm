"""Подача звіту до Центру тестування (БПР) по заході.

Подача -- факт про ЗАХІД, а не про людину: вона одним махом переводить усі
підтверджені реєстрації в «Завершено» і закриває захід для нових тестів і
сертифікатів. Тому тут масові `UPDATE`, а не цикл по реєстраціях: ORM-слухачі
`partner_events` на масовий UPDATE не спрацьовують, і це бажано -- подій
«статус змінено» партнер не розуміє. Листів учасникам перехід теж не шле
(`EmailService.send_status_change` тут не викликається свідомо).
"""
import logging
from datetime import date, datetime, timezone

from sqlalchemy import or_

from app.extensions import db
from app.models.registration import EventRegistration
from app.utils import ensure_utc

audit_logger = logging.getLogger('audit')


class ReportError(ValueError):
    """Подачу звіту відхилено (захід не закінчився, немає дат)."""


def is_closed(instance) -> bool:
    """Чи подано звіт по заходу (після цього тести і нові сертифікати закриті)."""
    return instance is not None and instance.bpr_report_submitted


def _actor(by_user) -> str:
    return getattr(by_user, 'email', None) or str(by_user)


def event_has_ended(instance) -> bool:
    """Чи закінчився захід: `end_date`, а без неї `start_date`, у минулому (UTC).

    Без жодної дати -- False. Єдине правило «захід закінчився» для подачі
    звіту і для масової відмітки «не з'явився».
    """
    finished_at = ensure_utc(instance.end_date or instance.start_date)
    return finished_at is not None and finished_at < datetime.now(timezone.utc)


def _event_ended(instance) -> bool:
    if instance.end_date is None and instance.start_date is None:
        raise ReportError('У заходу немає дати проведення')
    return event_has_ended(instance)


def submit_report(instance, submitted_on: date, by_user) -> int:
    """Перевести підтверджені реєстрації заходу в «Завершено».

    Повертає кількість переведених. Повторна подача нічого не змінює (0), на
    заході, що ще не закінчився, -- ReportError. Комітить сам.
    """
    if instance.bpr_report_submitted:
        return 0
    if not _event_ended(instance):
        raise ReportError('Захід ще не закінчився')

    moved = EventRegistration.query.filter(
        EventRegistration.instance_id == instance.id,
        EventRegistration.status == 'confirmed',
    ).update(
        {'status': 'completed', 'completed_by_report': True},
        synchronize_session='fetch',
    )
    instance.bpr_report_submitted_on = submitted_on
    instance.bpr_report_submitted_by_id = getattr(by_user, 'id', None)
    db.session.commit()
    audit_logger.info(
        'Admin %s submitted BPR report for instance %d: moved %d',
        _actor(by_user), instance.id, moved,
    )
    return moved


def undo_report(instance, by_user) -> int:
    """Скасувати подачу: повернути «Підтверджено» рівно тим, кого перевела подача.

    Рядок, де адмін уже відмітив присутність (`attended` = True), лишається
    «Завершено»: це його власне рішення. Прапорець `completed_by_report`
    скидається в усіх. Повертає кількість повернених. Комітить сам.
    """
    if not instance.bpr_report_submitted:
        return 0

    by_report = EventRegistration.query.filter(
        EventRegistration.instance_id == instance.id,
        EventRegistration.completed_by_report.is_(True),
    )
    returned = by_report.filter(
        EventRegistration.status == 'completed',
        or_(EventRegistration.attended.is_(None),
            EventRegistration.attended.is_(False)),
    ).update({'status': 'confirmed'}, synchronize_session='fetch')
    by_report.update({'completed_by_report': False}, synchronize_session='fetch')

    instance.bpr_report_submitted_on = None
    instance.bpr_report_submitted_by_id = None
    db.session.commit()
    audit_logger.info(
        'Admin %s undid BPR report for instance %d: returned %d',
        _actor(by_user), instance.id, returned,
    )
    return returned
