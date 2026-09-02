"""Заявки на повернення коштів: подання й рішення.

Гроші звідси не рухаються. Заявка -- це зафіксована дата звернення (§4.2)
плюс причина (§6.2); саме повернення проводить `payment_ops` зі сторінки
`/admin/refunds/...`. Розділення свідоме: одне місце, де система віддає
гроші, легше стерегти, ніж два.
"""
import logging
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.refund_request import (
    RefundRequest, STATUS_APPROVED, STATUS_NEW, STATUS_REJECTED,
)
from app.services import refund_policy

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

MAX_REASON = 2000
MAX_PAYOUT = 500


def open_request_for(order):
    """Відкрита заявка на це замовлення або None."""
    query = RefundRequest.query.filter_by(status=STATUS_NEW)
    if hasattr(order, 'online_course_id'):
        query = query.filter_by(enrollment_id=order.id)
    else:
        query = query.filter_by(registration_id=order.id)
    return query.first()


def latest_by_order(user):
    """Остання заявка користувача на кожне замовлення: дві мапи id -> заявка.

    Одним запитом на весь кабінет, а не перевіркою на рядок: кабінет і так
    найважча сторінка, і питати БД за кожен куплений курс означало б
    подорожчання, помітне вже на десятці замовлень.

    Саме ОСТАННЯ, а не лише відкрита: людина має бачити й результат --
    відмову з поясненням, а не тільки те, що заявка кудись пішла.
    """
    rows = (
        RefundRequest.query
        .filter_by(user_id=user.id)
        .order_by(RefundRequest.created_at.desc())
        .all()
    )
    by_registration, by_enrollment = {}, {}
    for row in rows:
        target = by_enrollment if row.enrollment_id else by_registration
        key = row.enrollment_id or row.registration_id
        # Перша побачена -- найновіша: список уже відсортований.
        target.setdefault(key, row)
    return by_registration, by_enrollment


def can_request(order):
    """Чи можна подати заявку на це замовлення.

    Повертає (True, None) або (False, причина для користувача). Причина
    формулюється так, щоб її можна було показати як є: людина має розуміти,
    чому кнопки немає, а не впиратись у мовчазну відсутність.
    """
    if order is None:
        return False, 'Замовлення не знайдено'
    if order.payment_status != 'paid':
        return False, 'Заявку можна подати лише за оплаченим замовленням'
    # Саме `refund_available`, а не `refund_remaining`: доплата різниці
    # тарифу при перенесенні прийшла окремим замовленням SUR-, і повернути
    # її за номером цього замовлення LiqPay не зможе. Заявка на суму, якої
    # ця форма не віддасть, лише завела б людину в очікування.
    if order.refund_available <= 0:
        return False, 'За цим замовленням уже повернуто всю суму'
    if open_request_for(order) is not None:
        return False, 'Заявку вже подано, вона на розгляді'
    return True, None


def create(order, user, reason, payout_details=None):
    """Прийняти заявку. Комітить.

    Знімок політики робиться ТУТ і від поточної миті: `created_at` заявки
    і є дата подання за §4.2. Якщо адмін відкриє її через три дні, сходинка
    вже не зміниться -- саме заради цього заявка й існує.
    """
    ok, problem = can_request(order)
    if not ok:
        return None, problem

    reason = (reason or '').strip()
    if not reason:
        return None, 'Вкажіть причину повернення'

    quote = refund_policy.quote_for(order)
    is_enrollment = hasattr(order, 'online_course_id')

    item = RefundRequest(
        registration_id=None if is_enrollment else order.id,
        enrollment_id=order.id if is_enrollment else None,
        user_id=user.id,
        reason=reason[:MAX_REASON],
        payout_details=(payout_details or '').strip()[:MAX_PAYOUT] or None,
        quoted_percent=quote.percent,
        quoted_amount=quote.amount,
        quoted_code=quote.code,
    )
    db.session.add(item)

    try:
        db.session.commit()
    except IntegrityError:
        # Дві заявки, подані одночасно: `can_request` вище перевіряє без
        # блокування, тож обидві її проходять, а часткова унікальність
        # зупиняє другу вже на коміті. Кажемо про це прямо -- інакше
        # людина побачить «спробуйте ще раз» і спробує ще раз.
        db.session.rollback()
        logger.info('Duplicate refund request from user %s', user.id)
        return None, 'Заявку вже подано, вона на розгляді'
    except Exception:
        db.session.rollback()
        logger.exception('Failed to store refund request for user %s', user.id)
        return None, 'Не вдалося зберегти заявку, спробуйте ще раз'

    audit_logger.info(
        'User %s submitted refund request #%s for %s (policy %s%%, %s UAH)',
        user.email, item.id, item.order_code, quote.percent, quote.amount,
    )
    _notify(item)
    return item, None


def _notify(item):
    """Лист учаснику («прийняли») і адмінам («розгляньте»). Best-effort.

    Збій пошти не має скасовувати вже прийняту заявку: вона лежить у черзі
    й видима адміну, а лист -- лише зручність.
    """
    from app.services.email_service import EmailService

    try:
        EmailService.send_refund_request_received(item)
    except Exception:
        logger.exception('Failed to queue refund-request receipt for #%s', item.id)
    try:
        EmailService.send_refund_request_notification(item)
    except Exception:
        logger.exception('Failed to notify admins about refund request #%s', item.id)


def reject(item, admin_user, note=None):
    """Відхилити заявку з поясненням. Комітить."""
    if not item.is_open:
        return False, 'Заявку вже розглянуто'

    item.decide(STATUS_REJECTED, admin_user, note)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to reject refund request #%s', item.id)
        return False, 'Помилка при збереженні'

    audit_logger.info('Admin %s rejected refund request #%s (%s): %s',
                      admin_user.email, item.id, item.order_code, note or '-')
    try:
        from app.services.email_service import EmailService
        EmailService.send_refund_request_declined(item)
    except Exception:
        logger.exception('Failed to queue rejection email for #%s', item.id)
    return True, 'Заявку відхилено, лист учаснику надіслано'


def mark_approved(item, admin_user, refunded_amount=None, note=None):
    """Позначити заявку задоволеною після проведеного повернення.

    Викликається зі сторінки повернення, коли гроші вже пішли. Окремого
    листа не шлемо: `refund_processed` уже повідомив і суму, і підставу.
    Не комітить -- лягає в ту саму транзакцію, що й решта.

    Якщо повернули МЕНШЕ, ніж просили, це записується в рішення. Інакше
    заявка на 1000 грн, задоволена поверненням 300, закрилась би як просто
    «задоволена», і різниця не лишила б по собі жодного сліду.
    """
    if not item.is_open:
        return
    if (note is None and refunded_amount is not None
            and item.quoted_amount is not None
            and Decimal(str(refunded_amount)) < Decimal(str(item.quoted_amount))):
        note = (f'Повернено {refunded_amount} грн із запитаних '
                f'{item.quoted_amount} грн')
    item.decide(STATUS_APPROVED, admin_user, note)
    audit_logger.info('Admin %s satisfied refund request #%s (%s), refunded %s',
                      admin_user.email, item.id, item.order_code,
                      refunded_amount if refunded_amount is not None else '-')


def pending_count():
    return RefundRequest.query.filter_by(status=STATUS_NEW).count()
