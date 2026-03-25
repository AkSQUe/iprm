"""
DB-aware payment operations.

Single code path for all payment status transitions.
Uses row-level locking to prevent race conditions.
"""
import logging
from datetime import datetime, timezone

from app.extensions import db
from app.models.registration import EventRegistration

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

STATUS_MAP = {
    'success': 'paid',
    'sandbox': 'paid',
    'failure': 'unpaid',
    'error': 'unpaid',
    'processing': 'pending',
    'wait_accept': 'pending',
    'reversed': 'refunded',
}

ALLOWED_TRANSITIONS = {
    'unpaid': {'pending', 'paid', 'refunded'},
    'pending': {'paid', 'refunded'},
    'paid': {'refunded'},
    'refunded': set(),
}

PERMANENT_ERRORS = frozenset({
    'invalid signature', 'unknown order_id', 'invalid order_id',
    'amount mismatch', 'invalid amount',
})


def _fail(msg):
    db.session.rollback()
    return False, msg


def _noop(msg):
    db.session.rollback()
    return True, msg


class PaymentOps:

    def __init__(self, liqpay_service):
        self.liqpay = liqpay_service

    def process_callback(self, data_base64, signature):
        if not self.liqpay.validate_callback_signature(data_base64, signature):
            logger.warning('LiqPay callback: invalid signature')
            return False, 'invalid signature'

        payload = self.liqpay.decode_callback(data_base64)
        order_id = payload.get('order_id', '')
        liqpay_status = payload.get('status', '')
        payment_id = str(payload.get('payment_id', ''))

        if not order_id.startswith('REG-'):
            logger.warning('LiqPay callback: unknown order_id: %s', order_id)
            return False, 'unknown order_id'

        try:
            reg_id = int(order_id.split('-', 1)[1])
        except (ValueError, IndexError):
            logger.warning('LiqPay callback: malformed order_id: %s', order_id)
            return False, 'invalid order_id'

        reg = db.session.query(EventRegistration).with_for_update().filter_by(
            id=reg_id
        ).first()
        if not reg:
            logger.warning('LiqPay callback: registration %d not found', reg_id)
            return False, 'registration not found'

        new_status = STATUS_MAP.get(liqpay_status)
        if not new_status:
            logger.warning('LiqPay callback: unknown status %s', liqpay_status)
            return _fail(f'unknown status: {liqpay_status}')

        if reg.payment_status == new_status and reg.payment_id == payment_id:
            return _noop('already processed')

        callback_amount = payload.get('amount')
        return self.update_payment_status(
            reg, new_status, payment_id, amount=callback_amount,
        )

    def update_payment_status(self, reg, new_status, payment_id=None, amount=None):
        if new_status == 'paid' and reg.payment_amount:
            try:
                if amount is not None and abs(float(amount) - float(reg.payment_amount)) > 0.01:
                    logger.warning(
                        'Payment amount mismatch REG-%d: expected %s, got %s',
                        reg.id, reg.payment_amount, amount,
                    )
                    return _fail('amount mismatch')
            except (TypeError, ValueError):
                logger.warning('Payment invalid amount for REG-%d', reg.id)
                return _fail('invalid amount')

        if new_status not in ALLOWED_TRANSITIONS.get(reg.payment_status, set()):
            logger.warning(
                'Payment invalid transition %s -> %s for REG-%d',
                reg.payment_status, new_status, reg.id,
            )
            return _noop('no-op transition')

        reg.payment_status = new_status
        if payment_id:
            reg.payment_id = payment_id

        if new_status == 'paid':
            reg.paid_at = datetime.now(timezone.utc)
            reg.status = 'confirmed'
        elif new_status == 'refunded':
            reg.status = 'cancelled'

        try:
            db.session.commit()
            logger.info('Payment REG-%d -> %s', reg.id, new_status)

            if new_status == 'paid':
                try:
                    from app.services.email_service import EmailService
                    EmailService.send_payment_confirmation(reg)
                except Exception:
                    logger.exception('Failed to queue payment email for REG-%d', reg.id)

            return True, 'ok'
        except Exception:
            logger.exception('Payment DB error for REG-%d', reg.id)
            return _fail('db error')

    def check_and_update(self, reg):
        order_id = f'REG-{reg.id}'
        status_data = self.liqpay.check_status(order_id)
        if not status_data:
            return False, 'api unavailable'

        lp_status = status_data.get('status', '')
        new_status = STATUS_MAP.get(lp_status)
        if not new_status or new_status == reg.payment_status:
            return True, 'no change'

        payment_id = str(status_data.get('payment_id', ''))
        callback_amount = status_data.get('amount')

        locked_reg = db.session.query(EventRegistration).with_for_update().filter_by(
            id=reg.id
        ).first()
        if not locked_reg:
            return False, 'registration not found'

        return self.update_payment_status(
            locked_reg, new_status, payment_id, amount=callback_amount,
        )

    def initiate_refund(self, reg, admin_user):
        locked_reg = db.session.query(EventRegistration).with_for_update().filter_by(
            id=reg.id
        ).first()
        if not locked_reg or locked_reg.payment_status != 'paid':
            return _fail('Повернення можливе тільки для оплачених реєстрацій')

        order_id = f'REG-{locked_reg.id}'
        result = self.liqpay.create_refund_request(order_id, float(locked_reg.payment_amount))

        if result is None:
            return _fail('Не вдалося зв\'єднатися з LiqPay API')

        lp_status = result.get('status', '')
        if lp_status in ('reversed', 'sandbox'):
            ok, msg = self.update_payment_status(locked_reg, 'refunded')
            if ok:
                audit_logger.info(
                    'Admin %s refunded REG-%d (%s UAH)',
                    admin_user.email, locked_reg.id, locked_reg.payment_amount,
                )
                return True, f'Повернення коштів ініційовано: {locked_reg.payment_amount} UAH'
            return False, f'Помилка оновлення статусу: {msg}'

        err = result.get('err_description', result.get('status', 'unknown'))
        logger.warning('LiqPay refund failed REG-%d: %s', locked_reg.id, err)
        return _fail(f'LiqPay відхилив повернення: {err}')
