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
from app.models.mixins import utcnow

logger = logging.getLogger(__name__)


def issue_for_instance(instance, issued_by=None):
    """Видати сертифікати всім тренерам заходу. Повертає список записів.

    Окремої пре-циклової перевірки балів БПР тут немає навмисно: усі
    передумови видачі (бали лектора, номер провайдера БПР, номер заходу
    БПР) `certificate_service.issue_lecturer_certificate` перевіряє сам і
    кидає `ValueError` з готовим людським текстом причини -- тримати ще
    одну перевірку тієї самої речі тут означало б два джерела правди, які
    рано чи пізно розійдуться.

    Спиняємось на ПЕРШОМУ збої, а не продовжуємо цикл по решті тренерів:
    - `ValueError` -- це завжди передумова заходу в цілому (бали, номер
      провайдера, номер заходу), а не конкретного тренера. Вона однаково
      завалить кожну наступну ітерацію, тож продовжувати цикл -- це лише
      наплодити однакових листів адмінам.
    - будь-який інший виняток -- технічний збій. `issue_lecturer_certificate`
      комітить сам на кожного тренера, тож збій на третьому тренері з п'яти
      лишив би перших двох із сертифікатами, а решту без -- захід у
      частковому стані, з якого немає чистого виходу. Тому й тут не
      продовжуємо, а повертаємо те, що встигло видатись, і сповіщаємо
      адмінів.
    """
    from app.services import certificate_service as cs

    trainers = instance.effective_trainers
    if not trainers:
        return []

    issued = []
    for trainer in trainers:
        try:
            issued.append(cs.issue_lecturer_certificate(
                instance, trainer, issued_by=issued_by))
        except ValueError as exc:
            db.session.rollback()
            _notify_failed(instance, str(exc))
            return issued
        except Exception:
            db.session.rollback()
            logger.exception(
                'Lecturer certificate issue failed: instance=%s trainer=%s',
                instance.id, trainer.id)
            _notify_failed(
                instance,
                'Технічний збій під час видачі -- подробиці в лозі сервера.',
            )
            return issued
    return issued


def recipient_email(trainer):
    """Куди слати сертифікат: анкета -> акаунт -> довідник.

    Анкета першою: цю адресу тренер вказав сам і сам підтримує. Довідникова
    остання -- її заповнює адмін, і вона найчастіше застаріває.
    """
    profile = trainer.profile
    candidates = (
        (profile.email if profile is not None else None),
        (trainer.user.email if trainer.user is not None else None),
        trainer.email,
    )
    for value in candidates:
        value = (value or '').strip()
        if value:
            return value
    return None


def send_pending(limit=50):
    """Розіслати сертифікати, які ще не пішли листом.

    Повертає (надіслано, пропущено_без_адреси). Черга -- `emailed_at IS NULL`.
    Збій на одному записі не ставить `emailed_at` і не зупиняє решту:
    наступний тік спробує знову. Ліміт -- щоб один тік не рендерив сотню PDF
    поспіль після довгого простою пошти.
    """
    from app.models.lecturer_certificate import LecturerCertificate
    from app.services.email_service import EmailService

    pending = (
        LecturerCertificate.query
        .filter(LecturerCertificate.emailed_at.is_(None))
        .order_by(LecturerCertificate.issued_at)
        .limit(limit)
        .all()
    )
    sent = skipped = 0
    for cert in pending:
        if cert.trainer is None:
            skipped += 1
            continue
        to_email = recipient_email(cert.trainer)
        if not to_email:
            # Свідомо НЕ ставимо emailed_at: запис лишається видимим як
            # «видано, не надіслано» і потрапляє в щоденний звіт адміну.
            skipped += 1
            continue
        try:
            EmailService.send_lecturer_certificate(cert, to_email)
        except Exception:
            db.session.rollback()
            logger.exception(
                'Failed to email lecturer certificate %s', cert.number)
            continue
        cert.emailed_at = utcnow()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception(
                'Failed to mark lecturer certificate %s as emailed', cert.number)
            continue
        sent += 1
    return sent, skipped


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
