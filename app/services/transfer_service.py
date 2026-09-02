"""Перенесення реєстрації на інше проведення.

Уся логіка тут; роути лишаються тонкими. Гроші звідси не рухаються --
повернення йде через чергу заявок, доплата через LiqPay-callback.

Правова рамка -- опублікована Політика (app/templates/main/refund.html):
§3.2 дає учаснику, ЯКОГО ПЕРЕНЕСЛИ МИ, право на участь без додаткової
оплати або на 100% повернення; §4.1 з його сіткою 100/50/25/0 діє лише
коли від участі відмовляється сам учасник. Тому `initiator` -- не довідкове
поле, а розгалуження всієї фічі.
"""
import logging

from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.registration_transfer import RegistrationTransfer
from app.models.mixins import utcnow
from app.utils import ensure_utc

logger = logging.getLogger(__name__)

# "Не пізніше ніж за 2 дні" -- 48 календарних годин. Політика оперує
# робочими днями лише в §3.3, і саме про дедлайн заявки на повернення, а не
# про перенесення. Одна константа: перехід на робочі дні -- одна правка.
TRANSFER_MIN_HOURS = 48


def hours_until(start_date):
    """Скільки годин лишилось до початку заходу. None -- дати немає."""
    if start_date is None:
        return None
    return (ensure_utc(start_date) - utcnow()).total_seconds() / 3600.0


def _registration_problems(reg):
    """Запобіжники, що не залежать від цільового заходу (1, 6, 7, 8, 9)."""
    problems = []

    if reg.status == 'cancelled':
        problems.append('Реєстрацію скасовано')

    hours = hours_until(reg.instance.start_date if reg.instance else None)
    if hours is not None and hours < TRANSFER_MIN_HOURS:
        problems.append(
            'До поточного заходу лишилось менше 2 діб — '
            'перенесення вже неможливе'
        )

    if reg.certificate is not None and not reg.certificate.revoked:
        problems.append('За реєстрацією вже видано сертифікат')

    if reg.quiz_passed_at is not None:
        problems.append('Учасник уже склав тест за цим заходом')

    open_transfer = RegistrationTransfer.query.filter_by(
        registration_id=reg.id, state=RegistrationTransfer.STATE_AWAITING,
    ).first()
    if open_transfer is not None:
        problems.append(
            'Попереднє перенесення ще очікує відповіді учасника'
        )

    return problems


def _target_problems(reg, target):
    """Запобіжники щодо цільового заходу (2, 3, 4, 5)."""
    problems = []

    if target.id == reg.instance_id:
        problems.append('Це той самий захід')

    hours = hours_until(target.start_date)
    if hours is None or hours < TRANSFER_MIN_HOURS:
        problems.append('До обраного заходу лишилось менше 2 діб')

    if target.status not in ('published', 'active'):
        problems.append('Захід недоступний для реєстрації')

    # Без цього перенесення падає на uq_user_instance_registration у момент
    # коміту -- вже після того, як лист пішов учаснику.
    duplicate = EventRegistration.query.filter_by(
        user_id=reg.user_id, instance_id=target.id,
    ).first()
    if duplicate is not None and duplicate.id != reg.id:
        problems.append('Учасник уже зареєстрований на цей захід')

    return problems


def check(registration, target_instance=None):
    """Причини, чому перенести не можна. Порожній список -- можна.

    Формулювання розраховані на показ як є: людина має розуміти, чому
    кнопки немає, а не впиратись у мовчазну відсутність.

    Без `target_instance` виконуються лише перевірки стану самої
    реєстрації -- саме так модалка вирішує, чи пропонувати заходи взагалі.
    """
    problems = _registration_problems(registration)
    if target_instance is not None:
        problems.extend(_target_problems(registration, target_instance))
    return problems


def eligible_instances(registration):
    """Проведення, на які цю реєстрацію можна перенести.

    Порядок -- за датою: адмін шукає найближчу придатну дату, а не курс.
    """
    if _registration_problems(registration):
        return []

    candidates = (
        CourseInstance.query
        .filter(CourseInstance.status.in_(('published', 'active')))
        .filter(CourseInstance.start_date.isnot(None))
        .order_by(CourseInstance.start_date.asc())
        .all()
    )
    return [
        item for item in candidates
        if not _target_problems(registration, item)
    ]
