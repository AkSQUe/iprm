import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen, Request

from app.extensions import db
from app.models.registration import EventRegistration

logger = logging.getLogger(__name__)

CHECKOUT_URL = 'https://www.liqpay.ua/api/3/checkout'
API_URL = 'https://www.liqpay.ua/api/request'

STATUS_MAP = {
    'success': 'paid',
    'sandbox': 'paid',
    'failure': 'unpaid',
    'error': 'unpaid',
    'processing': 'pending',
    'wait_accept': 'pending',
    'reversed': 'refunded',
}

class LiqPayService:

    def __init__(self, public_key, private_key, sandbox=True):
        self.public_key = public_key
        self.private_key = private_key
        self.sandbox = sandbox

    def _encode_params(self, params):
        raw = json.dumps(params, ensure_ascii=False).encode('utf-8')
        return base64.b64encode(raw).decode('ascii')

    def _generate_signature(self, data_base64):
        sign_str = (self.private_key + data_base64 + self.private_key).encode('utf-8')
        sha1 = hashlib.sha1(sign_str).digest()
        return base64.b64encode(sha1).decode('ascii')

    def validate_callback_signature(self, data_base64, received_signature):
        expected = self._generate_signature(data_base64)
        return hmac.compare_digest(expected, received_signature)

    def decode_callback(self, data_base64):
        raw = base64.b64decode(data_base64)
        return json.loads(raw)

    def create_payment_form(self, registration, result_url, server_url):
        params = {
            'version': 3,
            'public_key': self.public_key,
            'action': 'pay',
            'amount': str(float(registration.payment_amount)),
            'currency': 'UAH',
            'description': registration.event.title,
            'order_id': f'REG-{registration.id}',
            'result_url': result_url,
            'server_url': server_url,
            'language': 'uk',
        }
        if self.sandbox:
            params['sandbox'] = 1

        data = self._encode_params(params)
        signature = self._generate_signature(data)
        return data, signature, CHECKOUT_URL

    def process_callback(self, data_base64, signature):
        if not self.validate_callback_signature(data_base64, signature):
            logger.warning('LiqPay callback: invalid signature')
            return False, 'invalid signature'

        payload = self.decode_callback(data_base64)
        order_id = payload.get('order_id', '')
        liqpay_status = payload.get('status', '')
        payment_id = str(payload.get('payment_id', ''))

        if not order_id.startswith('REG-'):
            logger.warning('LiqPay callback: unknown order_id format: %s', order_id)
            return False, 'unknown order_id'

        reg_id = int(order_id.split('-', 1)[1])
        reg = db.session.get(EventRegistration, reg_id)
        if not reg:
            logger.warning('LiqPay callback: registration %d not found', reg_id)
            return False, 'registration not found'

        if reg.payment_status == 'paid' and reg.payment_id == payment_id:
            return True, 'already processed'

        new_status = STATUS_MAP.get(liqpay_status)
        if not new_status:
            logger.warning('LiqPay callback: unknown status %s', liqpay_status)
            return False, f'unknown status: {liqpay_status}'

        reg.payment_status = new_status
        reg.payment_id = payment_id

        if new_status == 'paid':
            reg.paid_at = datetime.now(timezone.utc)
            reg.status = 'confirmed'

        try:
            db.session.commit()
            logger.info('LiqPay callback: REG-%d -> %s', reg_id, new_status)
            return True, 'ok'
        except Exception:
            db.session.rollback()
            logger.exception('LiqPay callback: db error for REG-%d', reg_id)
            return False, 'db error'

    def check_status(self, order_id):
        params = {
            'version': 3,
            'public_key': self.public_key,
            'action': 'status',
            'order_id': order_id,
        }
        data = self._encode_params(params)
        signature = self._generate_signature(data)

        body = urlencode({'data': data, 'signature': signature}).encode('utf-8')
        req = Request(API_URL, data=body, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')

        try:
            with urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception:
            logger.exception('LiqPay check_status failed for %s', order_id)
            return None

    @property
    def is_configured(self):
        return bool(self.public_key and self.private_key)


def get_liqpay_service(app=None):
    from flask import current_app
    cfg = (app or current_app).config
    return LiqPayService(
        public_key=cfg.get('LIQPAY_PUBLIC_KEY', ''),
        private_key=cfg.get('LIQPAY_PRIVATE_KEY', ''),
        sandbox=cfg.get('LIQPAY_SANDBOX', True),
    )
