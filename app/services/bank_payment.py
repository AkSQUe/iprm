"""Підтвердження оплати переказом за банківською випискою.

Сайт mm-medic звіряє виписку і просить ІПРМ позначити реєстрацію (REG-) чи
замовлення онлайн-курсу (ONL-) оплаченим. Наслідки оплати -- ті самі, що й у
картки: статус, місце, лист «оплату отримано», запис у журналі. Усе це живе
в `PaymentOps`, тут -- лише правила допуску: що можна підтверджувати, а що
платіж не має права чіпати.

Ідемпотентність тримає журнал: рядок `source='bank'` із тим самим
`bank_tx_ref` означає, що цю операцію вже зараховано. Тому самому замовленню
це `duplicate`, іншому -- відмова `tx_used_elsewhere`. Рядок записаного
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
            'cancelled' | 'refunded' | 'amount_mismatch' |
            'tx_used_elsewhere' (операцію вже зараховано до ІНШОГО
            замовлення) | 'db_error'; інакше None.
    """
    status: str
    reason: Optional[str]
    order_ref: str


class BankPaymentUnavailable(Exception):
    """Тимчасова помилка БД там, де вердикту ще немає: відповідати відмовою
    не можна, бо відправник вважає відмову остаточною. Ендпоінт віддає 503,
    і відправник повторить запит."""


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


def _logged_owner(bank_tx_ref):
    """Кому зараховано цю банківську операцію: (registration_id, enrollment_id)
    або None, якщо операції в журналі ще немає."""
    return db.session.query(
        PaymentTransaction.registration_id, PaymentTransaction.enrollment_id,
    ).filter_by(source=SOURCE_BANK, payment_id=bank_tx_ref).first()


def _logged_outcome(owner, kind, object_id, order_ref,
                    same_order_status=STATUS_DUPLICATE):
    """Відповідь для вже зарахованої операції: те саме замовлення -- повтор
    (duplicate), інше -- відмова, бо рядок виписки не може закрити два
    замовлення (менеджер міг відвʼязати хибний збіг і привʼязати рядок
    до правильної реєстрації).

    same_order_status: що відповісти, коли рядок належить цьому ж замовленню.
    Для запасного шляху після збою PaymentOps це 'paid': перед викликом
    операції в журналі не було, тож рядок записав саме цей виклик."""
    registration_id, enrollment_id = owner
    owner_id = registration_id if kind == 'registration' else enrollment_id
    if owner_id == object_id:
        return BankPaymentResult(same_order_status, None, order_ref)
    return _refuse(order_ref, 'tx_used_elsewhere')


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

    owner = _logged_owner(bank_tx_ref)
    if owner is not None:
        return _logged_outcome(owner, kind, object_id, order_ref)

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
    # Замовлення без зафіксованої суми не має з чим звірятися: для LiqPay це
    # історичні рядки, а переказ без еталона підтверджувати не можна.
    expected = order.payment_amount
    if expected is None or _cents(amount) != _cents(expected):
        return _refuse(order_ref, 'amount_mismatch')

    # PaymentOps зберігає LiqPay-сервіс, але цей шлях його не чіпає: ні
    # перевірки підпису, ні запитів до LiqPay тут немає.
    # Оплата переказом -- це спосіб «рахунок», навіть якщо користувач
    # обирав картку: звіт по фінансах не має називати її LiqPay. Зміна
    # лягає в ту саму транзакцію, що й оплата; при відмові сесію відкочуємо.
    order.payment_method = 'invoice'
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
    # Невдача не повинна лишити в сесії непідтверджену зміну способу оплати.
    db.session.rollback()
    if message == 'amount mismatch':
        return _refuse(order_ref, 'amount_mismatch')
    # Унікальний індекс на bank_tx_ref відсік запис, що проскочив повз
    # _logged_owner, або збій стався вже ПІСЛЯ commit: сесію відкочено, і
    # рядок видно. Належить він цьому замовленню -- оплату зараховано саме
    # цим викликом (перед ним операції в журналі не було), тож це paid.
    try:
        owner = _logged_owner(bank_tx_ref)
    except SQLAlchemyError as exc:
        db.session.rollback()
        logger.warning('Bank payment fallback lookup failed for %s (%s): %s',
                       order_ref, bank_tx_ref, type(exc).__name__)
        raise BankPaymentUnavailable() from exc
    if owner is not None:
        return _logged_outcome(owner, kind, object_id, order_ref,
                               same_order_status=STATUS_PAID)
    return _refuse(order_ref, 'db_error')


# Походження оплати для API: рядок журналу -> що бачить партнер. `refund`
# сюди не входить свідомо: повернення не є способом оплати.
_PAID_VIA_BY_SOURCE = {
    'callback': 'liqpay',
    'status_check': 'liqpay',
    'manual': 'manual',
    SOURCE_BANK: 'bank',
}


# Пріоритет походження: картка сильніша за банк, банк -- за ручну позначку.
# Ручний рядок зʼявляється і тоді, коли адмін лише поправив дату вже
# оплаченої реєстрації, тож «останній виграє» видавав би картку за ручну.
_PAID_VIA_PRIORITY = ('liqpay', 'bank', 'manual')


def paid_via_map(kind: str, ids: list) -> dict:
    """Чим закрито оплату: {id: 'liqpay' | 'bank' | 'manual'}.

    kind: 'registration' чи 'enrollment'. Береться НАЙСИЛЬНІШЕ джерело серед
    рядків журналу з mapped_status='paid', а не останнє: liqpay (callback,
    status_check), інакше bank, інакше manual. Id без такого рядка в мапі
    немає. Один запит на весь список, без N+1.

    Чи оплачено зараз, мапа не знає: реєстрація, повернена пізніше, тут
    теж матиме значення -- відсікає це викликач за payment_status.
    """
    if not ids:
        return {}
    column = (PaymentTransaction.registration_id if kind == 'registration'
              else PaymentTransaction.enrollment_id)
    rows = (
        db.session.query(column, PaymentTransaction.source)
        .filter(column.in_(ids), PaymentTransaction.mapped_status == 'paid',
                PaymentTransaction.source.in_(list(_PAID_VIA_BY_SOURCE)))
        .all()
    )
    rank = {via: n for n, via in enumerate(_PAID_VIA_PRIORITY)}
    result = {}
    for owner_id, source in rows:
        via = _PAID_VIA_BY_SOURCE[source]
        if owner_id not in result or rank[via] < rank[result[owner_id]]:
            result[owner_id] = via
    return result
