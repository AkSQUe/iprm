"""Вхідний приймач MM Medic -> ІПРМ: оплата переказом за банківською випискою.

Сайт mm-medic читає виписку рахунку ІПРМ і, знайшовши переказ, що збігається
з реєстрацією, просить позначити її оплаченою. Підпис -- той самий, що й у
статусів резервів (див. mm_signature). Бізнес-відмова (вже оплачено, інша
сума, скасовано) -- це 200 із status='refused' і причиною, а не помилка
протоколу: відправнику потрібно відрізнити «не зараховано» від «не дійшло».

Контракт запиту (JSON):
  order_ref     'REG-<id>' | 'ONL-<id>'
  amount        сума переказу, > 0, до 2 знаків після коми, <= 99999999.99
  transacted_at ISO-8601 З часовим поясом (без поясу -- 400); точність
                завжди 'datetime': Privat Autoclient віддає час операції
  bank_tx_ref   стабільний ідентифікатор рядка виписки (mm-bt-<id>)
  actor         null -- збіг знайдено автоматично; рядок -- менеджер
                привʼязав операцію вручну (хто саме)

Відповідь 200: {status, reason, order_ref}.
  status 'paid'       -- оплату зараховано (reason null)
  status 'duplicate'  -- ця операція вже зарахована ТЕМ САМИМ замовленням
  status 'refused'    -- reason: bad_ref | not_found | already_paid |
                         cancelled | refunded | amount_mismatch |
                         tx_used_elsewhere (операцію вже зараховано до
                         іншого замовлення) | db_error
Відповідь 400: {status: 'malformed', field}.
Відповідь 503: {status: 'unavailable'} -- тимчасова помилка БД; повторити.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify

from app.api.mm_signature import verify_signed_request
from app.extensions import csrf, limiter
from app.services.bank_payment import (
    BankPaymentUnavailable, confirm_bank_payment, safe_rollback,
)

mm_bank_payment_bp = Blueprint(
    'mm_bank_payment', __name__, url_prefix='/api/partner/mm-medic')


_MAX_AMOUNT = Decimal('99999999.99')


class _BadField(Exception):
    def __init__(self, field):
        super().__init__(field)
        self.field = field


def _text(payload, field, max_len=255):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise _BadField(field)
    return value.strip()


def _amount(payload):
    raw = payload.get('amount')
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise _BadField('amount')
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        raise _BadField('amount')
    if not value.is_finite() or value <= 0 or value > _MAX_AMOUNT:
        raise _BadField('amount')
    # Копійки -- межа: 1500.004 не має округлюватися до збігу з 1500.00.
    if value != value.quantize(Decimal('0.01')):
        raise _BadField('amount')
    return value


def _moment(payload):
    raw = payload.get('transacted_at')
    if not isinstance(raw, str):
        raise _BadField('transacted_at')
    try:
        value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        raise _BadField('transacted_at')
    # Час без поясу двозначний: мовчки вважати його UTC означало б
    # зсунути дату оплати на 2-3 години.
    if value.tzinfo is None:
        raise _BadField('transacted_at')
    return value.astimezone(timezone.utc)


def _actor(payload):
    value = payload.get('actor')
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 255:
        raise _BadField('actor')
    return value.strip() or None


@mm_bank_payment_bp.route('/bank-payment', methods=['POST'])
@csrf.exempt
@limiter.limit('120 per minute')
def bank_payment():
    payload, error = verify_signed_request()
    if error:
        return error

    try:
        order_ref = _text(payload, 'order_ref', 64)
        amount = _amount(payload)
        transacted_at = _moment(payload)
        bank_tx_ref = _text(payload, 'bank_tx_ref')
        actor = _actor(payload)
    except _BadField as exc:
        return jsonify({'status': 'malformed', 'field': exc.field}), 400

    try:
        result = confirm_bank_payment(order_ref, amount, transacted_at,
                                      bank_tx_ref, actor=actor)
    except BankPaymentUnavailable:
        # Тимчасова помилка БД: відмова db_error для відправника остаточна,
        # а 5xx він повторює.
        return jsonify({'status': 'unavailable'}), 503
    finally:
        # Рядок замовлення заблоковано FOR UPDATE; ранні відмови сервісу сесію
        # не відкочують. Після успішного commit rollback нічого не скасовує,
        # а блокування й відкрита транзакція зникають одразу, не чекаючи
        # кінця запиту.
        safe_rollback()
    return jsonify({'status': result.status, 'reason': result.reason,
                    'order_ref': result.order_ref}), 200
