"""Підтвердження оплати переказом за банківською випискою.

Сайт mm-medic звіряє виписку і просить ІПРМ позначити реєстрацію (REG-) чи
замовлення онлайн-курсу (ONL-) оплаченим. Наслідки оплати -- ті самі, що й у
картки: статус, місце, лист «оплату отримано», запис у журналі. Усе це живе
в `PaymentOps`, тут -- лише правила допуску: що можна підтверджувати, а що
платіж не має права чіпати.

Ідемпотентність тримає журнал: рядок `source='bank'` із тим самим
`bank_tx_ref` означає, що цю операцію вже зараховано. Рядок записаного
замовлення блокується на час перевірки, тож два однакові запити одночасно
не пройдуть обидва.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.mixins import PAID_AT_DATETIME
from app.models.online_enrollment import OnlineEnrollment
from app.models.payment_transaction import PaymentTransaction
from app.models.registration import EventRegistration
from app.services.payment_ops import PaymentOps, parse_order_id

logger = logging.getLogger(__name__)

SOURCE_BANK = 'bank'

STATUS_PAID = 'paid'
STATUS_DUPLICATE = 'duplicate'
STATUS_REFUSED = 'refused'


@dataclass(frozen=True)
class BankPaymentResult:
    """Підсумок спроби підтвердити оплату.

    status: 'paid' | 'duplicate' | 'refused'
    reason: для 'refused' -- 'bad_ref' | 'not_found' | 'already_paid' |
            'cancelled' | 'refunded' | 'amount_mismatch' | 'db_error';
            інакше None.
    """
    status: str
    reason: Optional[str]
    order_ref: str


def _refuse(order_ref, reason):
    return BankPaymentResult(STATUS_REFUSED, reason, order_ref)


def _lock_order(kind, object_id):
    model = EventRegistration if kind == 'registration' else OnlineEnrollment
    return (
        db.session.query(model)
        .with_for_update().populate_existing()
        .filter_by(id=object_id).first()
    )


def _cents(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _already_logged(bank_tx_ref):
    return db.session.query(PaymentTransaction.id).filter_by(
        source=SOURCE_BANK, payment_id=bank_tx_ref,
    ).first() is not None


def confirm_bank_payment(order_ref: str, amount: Decimal, transacted_at: datetime,
                         bank_tx_ref: str,
                         actor: Optional[str] = None) -> BankPaymentResult:
    """Позначити замовлення оплаченим за банківською операцією.

    Порядок перевірок значущий: спершу «чи це наше замовлення», потім
    «чи цю операцію вже зараховано» (повтор не є помилкою), потім стани,
    у яких гроші зараховувати не можна, і лише тоді -- сама оплата.

    Обов'язок викликача: після повернення завершити сесію
    (`db.session.rollback()`). Рядок замовлення заблоковано FOR UPDATE, а
    ранні відмови сесію не відкочують -- без цього блокування висітиме до
    кінця запиту. Після успішного commit rollback нічого не скасовує.
    """
    kind, object_id = parse_order_id(order_ref or '')
    if kind not in ('registration', 'enrollment') or object_id is None:
        return _refuse(order_ref, 'bad_ref')

    # Відмови до виклику PaymentOps нічого не змінювали в сесії, тож і
    # відкочувати нічого: блокування рядка зніме кінець запиту.
    order = _lock_order(kind, object_id)
    if order is None:
        return _refuse(order_ref, 'not_found')

    if _already_logged(bank_tx_ref):
        return BankPaymentResult(STATUS_DUPLICATE, None, order_ref)

    reason = None
    if order.payment_status == 'refunded':
        reason = 'refunded'
    elif order.status == 'cancelled' or order.cancelled_at is not None:
        reason = 'cancelled'
    elif order.payment_status == 'paid':
        reason = 'already_paid'
    if reason:
        return _refuse(order_ref, reason)

    # Банк віддає точну суму, тож і звіряємо до копійки. Допуск у 0.01, який
    # check_amount залишає для LiqPay, тут пропустив би недоплату на копійку.
    expected = order.payment_amount
    if expected is not None and _cents(amount) != _cents(expected):
        return _refuse(order_ref, 'amount_mismatch')

    # PaymentOps зберігає LiqPay-сервіс, але цей шлях його не чіпає: ні
    # перевірки підпису, ні запитів до LiqPay тут немає.
    ops = PaymentOps(None)
    update = (ops.update_payment_status if kind == 'registration'
              else ops.update_enrollment_status)
    try:
        ok, message = update(
            order, 'paid', amount=amount, source=SOURCE_BANK,
            raw_payload={
                'bank_tx_ref': bank_tx_ref,
                'transacted_at': transacted_at.isoformat(),
                'actor': actor,
            },
            paid_at=(transacted_at, PAID_AT_DATETIME),
            txn_ref=bank_tx_ref,
        )
    except SQLAlchemyError:
        # Автоflush усередині PaymentOps упирається в унікальний індекс
        # bank_tx_ref раніше, ніж спрацює його власний try: ту саму операцію
        # встиг записати паралельний запит. Виняток виходить то як
        # IntegrityError, то як PendingRollbackError на наступному запиті
        # зламаної сесії, тому ловимо загальний клас.
        db.session.rollback()
        ok, message = False, 'db error'
    if ok:
        return BankPaymentResult(STATUS_PAID, None, order_ref)

    logger.warning('Bank payment refused for %s (%s): %s',
                   order_ref, bank_tx_ref, message)
    if message == 'amount mismatch':
        return _refuse(order_ref, 'amount_mismatch')
    # Унікальний індекс на bank_tx_ref відсік запис, що проскочив повз
    # _already_logged: PaymentOps відкотив сесію, і переможець уже видимий.
    if _already_logged(bank_tx_ref):
        return BankPaymentResult(STATUS_DUPLICATE, None, order_ref)
    return _refuse(order_ref, 'db_error')
