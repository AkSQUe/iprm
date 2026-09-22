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

# Через скільки годин виданий, але не надісланий сертифікат вважається
# "застряглим" і потрапляє у щоденний звіт адміну (а не в звичайний тік
# розсилки -- той намагається знову щоп'ять хвилин сам).
STUCK_AFTER_HOURS = 24


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

    Повертає (надіслано, пропущено). Черга -- `emailed_at IS NULL`. У
    "пропущено" потрапляють два різні випадки: немає тренера (сирітський
    запис) і є тренер, але жодної його адреси -- обидва не надсилаються,
    але з різних причин, тож рахунок спільний, а причина видна лише в лозі.
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
            # trainer_id -- nullable з ondelete='SET NULL': сертифікат є
            # незмінним знімком видачі й переживає видалення тренера з
            # довідника, тож цей рядок -- не теоретичний, а справжній
            # сирітський запис, якого нема кому надіслати.
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


def blocking_reason(instance):
    """Чому видача на цей захід неможлива -- текстом, або None, якщо можлива.

    Передумов три (бали БПР тренеру, номер провайдера БПР, номер заходу
    БПР), і кожна вже несе точне пояснення у своєму ValueError. Питаємо саме
    `certificate_service`, а не повторюємо перевірки тут: дві копії однієї
    умови розходяться, і тоді звіт адміну каже одне, а видача падає з іншого.
    """
    from app.services import certificate_service as cs

    try:
        cs._bpr_number_inputs(instance)
        cs._lecturer_points(instance)
    except ValueError as exc:
        return str(exc)
    return None


def issue_missing():
    """Добрати сертифікати завершеним заходам. Повертає кількість виданих.

    Покриває два реальні сценарії: бали БПР внесли вже після завершення
    заходу; тренера додали до складу після завершення. Обидва лишали б
    тренера без документа назавжди, бо тригер спрацьовує рівно один раз.
    """
    from app.models.course_instance import CourseInstance
    from app.models.lecturer_certificate import LecturerCertificate

    instances = CourseInstance.query.filter_by(status='completed').all()
    if not instances:
        return 0

    # Один запит на всі завершені заходи заздалегідь, а не по одному на
    # ітерацію циклу: джоба щоденна й ходить по всіх завершених заходах,
    # яких з часом стає багато, а сам запит -- одна пара колонок.
    rows = (
        db.session.query(LecturerCertificate.instance_id,
                          LecturerCertificate.trainer_id)
        .filter(LecturerCertificate.instance_id.in_(
            [inst.id for inst in instances]))
        .all()
    )
    issued_by_instance = {}
    for instance_id, trainer_id in rows:
        issued_by_instance.setdefault(instance_id, set()).add(trainer_id)

    issued = 0
    for instance in instances:
        trainers = instance.effective_trainers
        if not trainers:
            continue
        have = issued_by_instance.get(instance.id, set())
        if all(t.id in have for t in trainers):
            continue
        issued += len(issue_for_instance(instance))
    return issued


def daily_maintenance():
    """Добір пропущених + звіт адмінам про те, що застрягло.

    Звіт іде ЛИШЕ коли є про що казати: щоденний лист «усе гаразд» перестають
    читати, і разом із ним перестають помічати справжні.
    """
    from datetime import timedelta

    from app.models.course_instance import CourseInstance
    from app.models.lecturer_certificate import LecturerCertificate
    from app.services.email_service import EmailService

    issued = issue_missing()

    cutoff = utcnow() - timedelta(hours=STUCK_AFTER_HOURS)
    stuck = (
        LecturerCertificate.query
        .filter(LecturerCertificate.emailed_at.is_(None),
                LecturerCertificate.issued_at < cutoff)
        .all()
    )
    blocked = [
        inst for inst in CourseInstance.query.filter_by(status='completed').all()
        if inst.effective_trainers and blocking_reason(inst) is not None
    ]
    if stuck or blocked:
        try:
            EmailService.notify_lecturer_certificate_report(stuck, blocked)
        except Exception:
            db.session.rollback()
            logger.exception('Failed to send lecturer certificate report')
    return {'issued': issued, 'stuck': len(stuck), 'blocked': len(blocked)}
