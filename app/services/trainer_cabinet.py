"""Кабінет тренера: заходи тренера, лічильники реєстрацій, анкета, FAQ.

Тренер бачить лише ЧИСЛА реєстрацій, без персональних даних учасників.
Переходи статусів пропозиції курсу -- тільки тут; функції змінюють об'єкт
і не комітять (commit і лист робить маршрут).
"""
import re
from datetime import datetime, timezone

from markupsafe import escape
from sqlalchemy import and_, case, exists, func, or_
from sqlalchemy.orm import joinedload

from app.data.trainer_faq import DEFAULT_TRAINER_FAQ_HTML
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.registration import EventRegistration
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_links import course_instance_trainers, course_trainers
from app.models.trainer_profile import TrainerProfile
from app.utils import kyiv_day_start_utc, sanitize_rich_text


class ProposalTransitionError(ValueError):
    """Недопустимий перехід статусу пропозиції курсу."""


def _not_finished_before_today(now=None):
    """Захід ще не закінчився до початку сьогоднішньої київської доби.

    Порівнюємо кінець (для одноденного -- початок) з ПОЧАТКОМ дня, а не з
    поточним моментом: інакше захід зникав би з кабінету, щойно почався, --
    саме тоді, коли тренер на нього дивиться. Багатоденний тримається до
    свого останнього дня. Дата без старту лишається в списку (її ще
    призначать).
    """
    ends = func.coalesce(CourseInstance.end_date, CourseInstance.start_date)
    return or_(CourseInstance.start_date.is_(None), ends >= kyiv_day_start_utc(now))


def upcoming_instances(trainer, now=None):
    """Сьогоднішні й майбутні published/active дати, де тренер серед effective_trainers.

    Повторює CourseInstance.effective_trainers у SQL: тренер призначений на
    саму дату, АБО на курс -- і тоді лише якщо в дати немає власних тренерів
    (власний список повністю перекриває курсовий).
    """
    cit = course_instance_trainers
    on_instance = exists().where(
        cit.c.instance_id == CourseInstance.id, cit.c.trainer_id == trainer.id)
    has_own = exists().where(cit.c.instance_id == CourseInstance.id)
    on_course = exists().where(
        course_trainers.c.course_id == CourseInstance.course_id,
        course_trainers.c.trainer_id == trainer.id)
    return (
        CourseInstance.query
        .options(joinedload(CourseInstance.course), joinedload(CourseInstance.city))
        .filter(
            CourseInstance.status.in_(('published', 'active')),
            _not_finished_before_today(now),
            or_(on_instance, and_(~has_own, on_course)),
        )
        .order_by(CourseInstance.start_date.is_(None), CourseInstance.start_date)
        .all()
    )


def registration_counts(instance_ids):
    """{instance_id: {total, paid, online, offline}} одним запитом.

    Скасовані не рахуються. Формат участі -- той самий ланцюжок, що в
    EventRegistration.effective_participation_format: власне поле -> тариф
    -> формат заходу (гібрид без уточнення -> очно).

    case() тут -- по колонках reg/CourseInstance/InstanceTariff, а не по
    результату OUTER JOIN у вигляді NULL-рядка: коли в реєстрації немає
    тарифу, InstanceTariff.event_format для неї -- NULL, і порівняння
    `NULL == 'online'` дає SQL UNKNOWN (не True), тож case() коректно йде
    до наступної гілки (event_format заходу). На SQLite поведінка та сама.
    """
    if not instance_ids:
        return {}
    reg = EventRegistration
    is_online = case(
        (reg.participation_format == 'online', 1),
        (reg.participation_format == 'offline', 0),
        (InstanceTariff.event_format == 'online', 1),
        (InstanceTariff.event_format == 'offline', 0),
        (CourseInstance.event_format == 'online', 1),
        else_=0,
    )
    rows = (
        db.session.query(
            reg.instance_id,
            func.count(reg.id),
            func.sum(case((reg.payment_status == 'paid', 1), else_=0)),
            func.sum(is_online),
        )
        .join(CourseInstance, CourseInstance.id == reg.instance_id)
        .outerjoin(InstanceTariff, InstanceTariff.id == reg.tariff_id)
        .filter(reg.instance_id.in_(instance_ids), reg.status != 'cancelled')
        .group_by(reg.instance_id)
        .all()
    )
    result = {}
    for instance_id, total, paid, online in rows:
        online = int(online or 0)
        result[instance_id] = {
            'total': int(total), 'paid': int(paid or 0),
            'online': online, 'offline': int(total) - online,
        }
    return result


def trainer_courses(trainer):
    """Активні курси, де тренер призначений на рівні курсу."""
    return (
        Course.query
        .join(course_trainers, course_trainers.c.course_id == Course.id)
        .filter(course_trainers.c.trainer_id == trainer.id, Course.is_active.is_(True))
        .order_by(Course.title)
        .all()
    )


def submit_proposal(proposal):
    if proposal.status != TrainerCourseProposal.DRAFT:
        raise ProposalTransitionError('Надіслати можна лише чернетку')
    proposal.status = TrainerCourseProposal.SUBMITTED
    proposal.submitted_at = datetime.now(timezone.utc)
    # Коментар стосувався ПОПЕРЕДНЬОЇ версії (та, яку повернули); лишити
    # його -- значить показувати куратору й тренеру зауваження, яке вже
    # виправлене цим-таки надсиланням.
    proposal.curator_comment = None


def accept_proposal(proposal):
    if proposal.status != TrainerCourseProposal.SUBMITTED:
        raise ProposalTransitionError('Прийняти можна лише надіслану пропозицію')
    proposal.status = TrainerCourseProposal.ACCEPTED


def unaccept_proposal(proposal):
    """Скасувати прийняття: пропозиція знову на розгляді.

    «Прийнято» натискають одним кліком, а тренер після нього вже не може
    нічого змінити -- помилковий клік без цього переходу був би остаточним.
    Повертаємо саме в submitted, а не в draft: тренер нічого не просив
    змінювати, куратор лише передумав.
    """
    if proposal.status != TrainerCourseProposal.ACCEPTED:
        raise ProposalTransitionError('Скасувати можна лише прийняту пропозицію')
    proposal.status = TrainerCourseProposal.SUBMITTED


def return_proposal(proposal, comment):
    if proposal.status != TrainerCourseProposal.SUBMITTED:
        raise ProposalTransitionError('Повернути можна лише надіслану пропозицію')
    proposal.status = TrainerCourseProposal.DRAFT
    proposal.curator_comment = (comment or '').strip() or None


def contract_email(settings):
    """Куди тренер надсилає договір: окремий email або загальний email сайту."""
    return (settings.trainer_contract_email or '').strip() or (settings.email or '')


def faq_source(settings):
    """Сирий HTML FAQ: збережений в адмінці або текст за замовчуванням."""
    return (settings.trainer_faq_html or '').strip() or DEFAULT_TRAINER_FAQ_HTML


# Коли адреси немає зовсім, «надішліть на адресу {email}» перетворювалось на
# «надішліть на адресу .». Текст FAQ -- український контент з адмінки, тож і
# підстановка українська: перекладений шматок посеред українського абзацу
# читався б гірше за будь-яку з мов.
_FAQ_EMAIL_PHRASE = re.compile(r'на\s+адресу\s*\{email\}')
_FAQ_NO_EMAIL_PHRASE = 'на адресу, яку уточніть у куратора'
_FAQ_NO_EMAIL = 'адресу уточніть у куратора'


def faq_html(settings):
    """Безпечний HTML FAQ з підставленим email для договорів."""
    email = contract_email(settings)
    html = faq_source(settings)
    if email:
        html = html.replace('{email}', str(escape(email)))
    else:
        html = _FAQ_EMAIL_PHRASE.sub(_FAQ_NO_EMAIL_PHRASE, html).replace('{email}', _FAQ_NO_EMAIL)
    return sanitize_rich_text(html)


def requisites_snapshot(profile):
    """Розшифровані реквізити анкети до правки: {поле: значення}."""
    return {name: (getattr(profile, name) or '') for name in TrainerProfile.SENSITIVE_FIELDS}


def changed_requisites(before, profile):
    """Назви реквізитів, що змінились відносно знімка, у порядку SENSITIVE_FIELDS."""
    return [name for name in TrainerProfile.SENSITIVE_FIELDS
            if (getattr(profile, name) or '') != before.get(name, '')]


def get_or_create_profile(trainer):
    if trainer.profile is None:
        trainer.profile = TrainerProfile(trainer_id=trainer.id)
        db.session.flush()
    return trainer.profile
