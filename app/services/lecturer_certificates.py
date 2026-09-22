"""Автовидача, розсилка й добір сертифікатів лектора.

Оркестрація живе тут, а не в certificate_service: той модуль уже великий і
відповідає за самі документи (номери, знімки, рендер), а це — правила
життєвого циклу навколо них.

Перехід заходу в 'completed' робить лише INSERT записів. Рендер PDF
(WeasyPrint, секунда-дві на документ) і розсилка винесені у фонові джоби:
запит адміна не має на них чекати, а збій рендера не має відкочувати зміну
статусу.
"""
import logging

from app.extensions import db

logger = logging.getLogger(__name__)


def issue_for_instance(instance, issued_by=None):
    """Видати сертифікати всім тренерам заходу. Повертає список записів.

    Бали БПР перевіряються ОДИН раз до циклу: вони в заході одні на всіх, тож
    або падають усі, або ніхто. Перевірка всередині циклу дала б захід із
    частиною виданих сертифікатів — стан, з якого немає чистого виходу.

    Немає балів -> нічого не видається, адмінам іде лист, захід лишається в
    черзі добору (`issue_missing`): щойно бали внесуть, наступний тік видасть
    сертифікати сам.
    """
    from app.services import certificate_service as cs

    trainers = instance.effective_trainers
    if not trainers:
        return []

    if instance.effective_lecturer_points is None:
        _notify_failed(
            instance,
            'Не задано бали БПР тренеру (Адмінка -> Курс або конкретне '
            'проведення -> редагувати).',
        )
        return []

    issued = []
    for trainer in trainers:
        try:
            issued.append(cs.issue_lecturer_certificate(
                instance, trainer, issued_by=issued_by))
        except Exception:
            db.session.rollback()
            logger.exception(
                'Lecturer certificate issue failed: instance=%s trainer=%s',
                instance.id, trainer.id)
    return issued


def _notify_failed(instance, reason):
    """Лист адмінам. Best-effort: збій сповіщення нічого не відкочує."""
    from app.services.email_service import EmailService
    try:
        EmailService.notify_lecturer_certificate_failed(instance, reason)
    except Exception:
        db.session.rollback()
        logger.exception(
            'Failed to notify admins about lecturer cert failure: instance=%s',
            instance.id)
