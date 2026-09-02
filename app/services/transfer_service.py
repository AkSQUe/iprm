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
from decimal import Decimal

from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.registration_transfer import (
    DECISION_SURCHARGE, INITIATOR_ORGANIZER, RegistrationTransfer,
)
from app.models.refund_request import RefundRequest, STATUS_NEW
from app.models.mixins import utcnow
from app.services import refund_policy, refund_requests, registration_service
from app.services.refund_requests import MAX_PAYOUT, MAX_REASON
from app.utils import ensure_utc

logger = logging.getLogger(__name__)

# "Не пізніше ніж за 2 дні" -- 48 календарних годин. Політика оперує
# робочими днями лише в §3.3, і саме про дедлайн заявки на повернення, а не
# про перенесення. Одна константа: перехід на робочі дні -- одна правка.
TRANSFER_MIN_HOURS = 48

# Коди відмов для публічних роутів. Саме коди, а не готовий текст: `_()`
# навколо змінної нічого не перекладає (каталог не має такого msgid), тож
# літерали лишаються в роуті, а сервіс каже лише, ЩО сталось.
ERROR_ANSWERED = 'answered'
ERROR_NOT_FOUND = 'not_found'
ERROR_NOT_ELIGIBLE = 'not_eligible'


def hours_until(start_date):
    """Скільки годин лишилось до початку заходу. None -- дати немає."""
    if start_date is None:
        return None
    return (ensure_utc(start_date) - utcnow()).total_seconds() / 3600.0


def unpaid_surcharge_condition():
    """Умова «доплату запросили, а вона не надійшла» -- одна на весь проєкт.

    Тією самою умовою живляться три різні місця: запобіжник 11 нижче,
    плашка в списку реєстрацій і фільтр «Доплата: не надійшла». Три копії
    розійшлися б при першій же правці, і розбіжність жила б саме там, де
    її найважче помітити -- у грошах.
    """
    return (
        RegistrationTransfer.tariff_decision == DECISION_SURCHARGE,
        RegistrationTransfer.surcharge_paid_at.is_(None),
    )


def unpaid_surcharge_amounts(registration_ids):
    """{registration_id: сума незакритої доплати} -- ОДНИМ запитом.

    Батчем, а не властивістю моделі в циклі шаблону: поштучний виклик на
    кожен рядок таблиці -- це рівно той N+1, від якого стереже
    test_page_does_not_grow_with_participants.
    """
    ids = list(registration_ids)
    if not ids:
        return {}
    return dict(db.session.query(
        RegistrationTransfer.registration_id, RegistrationTransfer.difference,
    ).filter(
        RegistrationTransfer.registration_id.in_(ids),
        *unpaid_surcharge_condition(),
    ).all())


def _registration_problems(reg):
    """Запобіжники, що не залежать від цільового заходу (1, 6, 7, 8, 9-11)."""
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

    # Інакше друге перенесення з `refund_diff` мовчки зменшило б уже подану
    # заявку учасника на повне повернення до різниці тарифів --
    # _open_refund_request ОНОВЛЮЄ, а не додає другу.
    open_refund = RefundRequest.query.filter_by(
        registration_id=reg.id, status=STATUS_NEW,
    ).first()
    if open_refund is not None:
        problems.append(
            'За реєстрацією вже є відкрита заявка на повернення — '
            'спершу розгляньте її'
        )

    # Друге перенесення при незакритій доплаті переоцінює РІЗНИЦЮ: вона
    # рахується від payment_amount, а той ще не ввібрав першу сходинку
    # (apply_surcharge додає суму лише коли гроші надійшли). 1000 -> 1500
    # (борг 500) -> 2000 дало б другу різницю 1000 замість 500, обидва
    # посилання SUR- живі 30 днів, і оплата обох дала б 2500 за захід на
    # 2000. Запобіжник 9 тут не рятує: стан awaiting_consent зникає в мить
    # згоди учасника, а тихе перенесення в нього й не заходить.
    unpaid_surcharge = RegistrationTransfer.query.filter(
        RegistrationTransfer.registration_id == reg.id,
        *unpaid_surcharge_condition(),
    ).first()
    if unpaid_surcharge is not None:
        problems.append(
            'За попереднім перенесенням не надійшла доплата — '
            'спершу закрийте її'
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


audit_logger = logging.getLogger('audit')


def _money(value):
    return Decimal(str(value or 0))


def _clean(text, limit):
    """Порожній рядок -> None: лист вирішує за NULL, чи рендерити блок."""
    text = (text or '').strip()
    return text[:limit] if text else None


def _open_refund_request(transfer, amount, reason, quoted_code, percent=None):
    """Завести (або оновити) заявку на повернення від імені перенесення.

    Повертає (заявка, None) або (None, причина відмови).

    Партіальний унікальний індекс uq_refund_requests_open_registration
    дозволяє ОДНУ відкриту заявку на реєстрацію. Тож коли на різницю тарифу
    вже висить заявка, а учасник просить повернути все, ми ОНОВЛЮЄМО її, а
    не створюємо другу: інакше сценарій падає IntegrityError рівно в момент
    кліку учасника. Саме тому ворота `refund_requests.can_request`
    перевіряються ЛИШЕ перед створенням НОВОЇ заявки: серед них є «заявку
    вже подано», і на шляху оновлення воно відбивало б само себе.

    Нова заявка проходить ті самі ворота, що й заявка з кабінету. Без них
    перенесення НЕОПЛАЧЕНОЇ реєстрації з `refund_diff` заводило б заявку на
    повернення грошей, яких ми не отримували: `payment_amount` ставиться
    при реєстрації, ДО оплати.

    Не комітить -- caller відповідає за commit і за розсилку (_notify).
    """
    reg = transfer.registration
    existing = RefundRequest.query.filter_by(
        registration_id=reg.id, status=STATUS_NEW,
    ).first()

    reason = (reason or '').strip()[:MAX_REASON]
    if not reason:
        # §6.2 Політики: заявка без письмової причини -- не заявка.
        return None, 'Вкажіть причину повернення'

    if existing is not None:
        existing.reason = reason
        existing.quoted_amount = amount
        existing.quoted_percent = percent
        existing.quoted_code = quoted_code
        return existing, None

    ok, problem = refund_requests.can_request(reg)
    if not ok:
        return None, problem

    item = RefundRequest(
        registration_id=reg.id,
        enrollment_id=None,
        user_id=reg.user_id,
        reason=reason,
        quoted_percent=percent,
        quoted_amount=amount,
        quoted_code=quoted_code,
    )
    db.session.add(item)
    db.session.flush()
    return item, None


def accept(transfer):
    """Учасник погодився на перенесення. Комітить.

    Ідемпотентно за станом: повторний POST із тієї ж сторінки (або
    подвійний клік) не має переписувати дату відповіді.
    """
    if not transfer.is_open:
        return False, 'Ви вже відповіли на цю пропозицію'

    transfer.state = RegistrationTransfer.STATE_ACCEPTED
    transfer.responded_at = utcnow()
    reg = transfer.registration
    if reg is not None and reg.status == 'pending':
        reg.status = 'confirmed'
    db.session.commit()

    audit_logger.info('Transfer #%s accepted by participant', transfer.id)
    return True, 'Дякуємо, участь підтверджено'


def request_refund(transfer, reason, payout_details=None):
    """Учасник обрав повернення коштів замість перенесення. Комітить.

    Сума залежить від того, ЧИЯ була ініціатива:
    * organizer   -- 100% сплаченого (§3.2), бо перенесли ми;
    * participant -- сітка §4.1 через refund_policy.
    """
    if not transfer.is_open:
        return None, ERROR_ANSWERED

    reg = transfer.registration
    if reg is None:
        return None, ERROR_NOT_FOUND

    if transfer.initiator == INITIATOR_ORGANIZER:
        percent = 100
        amount = _money(reg.payment_amount)
        code = 'transfer_organizer'
    else:
        quote = refund_policy.quote_registration(reg)
        percent = quote.percent
        amount = quote.amount
        code = quote.code

    item, problem = _open_refund_request(transfer, amount, reason, code, percent)
    if item is None:
        # Реєстрація не в тому стані, щоб за нею щось повертати (не
        # оплачена, вже повернута). Стан перенесення не чіпаємо: людині
        # лишається натиснути «Погоджуюсь».
        db.session.rollback()
        logger.info('Transfer #%s: refund claim refused (%s)',
                    transfer.id, problem)
        return None, ERROR_NOT_ELIGIBLE

    if payout_details:
        item.payout_details = payout_details.strip()[:MAX_PAYOUT] or None

    transfer.state = RegistrationTransfer.STATE_REFUND_REQUESTED
    transfer.responded_at = utcnow()
    transfer.refund_request_id = item.id
    db.session.commit()

    audit_logger.info(
        'Transfer #%s: participant requested refund, request #%s (%s%%, %s)',
        transfer.id, item.id, percent, amount,
    )

    # Ті самі два листи, що й у заявки з кабінету: квитанція учаснику й
    # сигнал менеджеру. Раніше йшов лише другий, тож людина не мала
    # жодного підтвердження, що її звернення прийняли.
    refund_requests._notify(item)

    return item, None


def execute(registration, *, target_instance, initiator, tariff=None,
            tariff_decision='keep', reason=None, note=None, announced=False,
            admin_user=None):
    """Перенести реєстрацію. Комітить.

    Переїзд негайний і для тихого, і для голосного режиму: людину, яку ми
    перенесли, не можна лишати на заході, якого не буде, поки вона не
    відповість на лист. Згода лише підтверджує вже здійснений переїзд.
    """
    problems = check(registration, target_instance)
    if problems:
        raise ValueError(problems)

    if (initiator == INITIATOR_ORGANIZER
            and tariff_decision == DECISION_SURCHARGE):
        # Дублює CHECK у БД -- свідомо: сервіс має відмовити зрозумілим
        # текстом, а не IntegrityError на коміті.
        raise ValueError([
            'Перенесення з ініціативи Організатора не допускає доплати '
            '(§3.2 Політики)'
        ])

    from_instance_id = registration.instance_id
    old_amount = _money(registration.payment_amount)
    if tariff is not None:
        new_amount = _money(tariff.price)
    else:
        new_amount = _money(target_instance.price)

    difference = new_amount - old_amount
    # Напрямок різниці мусить відповідати рішенню, інакше "повернути
    # різницю" на ДОРОЖЧОМУ тарифі тихо не зробило б нічого, а адмін був би
    # певен, що заявку заведено.
    if tariff_decision == 'refund_diff' and difference >= 0:
        raise ValueError([
            'Повертати нічого: новий тариф не дешевший за сплачену суму'
        ])
    if tariff_decision == DECISION_SURCHARGE and difference <= 0:
        raise ValueError([
            'Доплачувати нічого: новий тариф не дорожчий за сплачену суму'
        ])

    # Знулення обов'язкове: assign_place_number ідемпотентний і на
    # заповненому номері одразу поверне старий -- реєстрація приїхала б на
    # новий захід із чужим номером, порушивши uq_registrations_instance_place.
    registration.place_number = None
    registration.instance_id = target_instance.id
    registration.tariff_id = tariff.id if tariff is not None else None

    if (registration.payment_status == 'paid'
            and registration.status != 'cancelled'):
        try:
            registration_service.assign_place_number(registration)
        except Exception:
            logger.exception(
                'Failed to assign place_number for REG-%s after transfer',
                registration.id,
            )

    transfer = RegistrationTransfer(
        registration_id=registration.id,
        from_instance_id=from_instance_id,
        to_instance_id=target_instance.id,
        initiator=initiator,
        announced=bool(announced),
        reason=_clean(reason, 500),
        note=_clean(note, 5000),
        tariff_decision=tariff_decision,
        to_tariff_id=tariff.id if tariff is not None else None,
        old_amount=old_amount,
        new_amount=new_amount,
        difference=difference,
        state=(RegistrationTransfer.STATE_AWAITING if announced
               else RegistrationTransfer.STATE_APPLIED),
        created_by_id=admin_user.id if admin_user is not None else None,
    )
    if announced:
        transfer.issue_consent_token()
    db.session.add(transfer)

    request = refund_problem = None
    if tariff_decision == 'refund_diff' and transfer.difference < 0:
        db.session.flush()  # transfer.id потрібен для аудиту заявки
        request, refund_problem = _open_refund_request(
            transfer,
            amount=abs(transfer.difference),
            reason=(f'Різниця тарифів при перенесенні на '
                    f'{target_instance.course.title if target_instance.course else "інший захід"}'),
            quoted_code='transfer_diff',
            percent=None,
        )
        if request is not None:
            transfer.refund_request_id = request.id
        else:
            # Сам переїзд легітимний -- не скасовуємо його через те, що
            # повертати нічого. Але адмін мусить це побачити: інакше він
            # певен, що заявку заведено, і чекає її в черзі.
            logger.info('Transfer for REG-%s: refund claim skipped (%s)',
                        registration.id, refund_problem)

    db.session.commit()

    audit_logger.info(
        'Transfer #%s: REG-%s moved %s -> %s by %s (%s, %s, diff %s)',
        transfer.id, registration.id, from_instance_id, target_instance.id,
        admin_user.email if admin_user is not None else 'system',
        initiator, tariff_decision, transfer.difference,
    )

    if request is not None:
        # Заявка на різницю -- така сама заявка, як із кабінету, і мусить
        # дійти і до менеджера, і до учасника. Після коміту: лист про
        # рядок, якого ще немає в базі, посилався б у порожнечу.
        refund_requests._notify(request)

    if announced:
        # Best-effort: збій пошти не має скасовувати вже здійснений переїзд.
        # Посилання лишається в адмінці, лист можна надіслати повторно.
        from app.services.email_service import EmailService
        try:
            EmailService.send_transfer_offer(transfer)
        except Exception:
            logger.exception(
                'Failed to queue transfer offer for #%s', transfer.id)

    # Транзиторна позначка (не колонка): роут показує її адміну флешем.
    # Кортеж тут був би гірший -- `execute` читають як «перенести», і
    # другий елемент, потрібний одному викликачу, губився б у решті.
    transfer.refund_claim_problem = refund_problem
    return transfer
