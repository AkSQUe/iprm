"""
LiqPay protocol layer (pure, no DB dependency).

Handles: encoding, signatures, payment form generation, API calls.
Business logic (status transitions, DB updates) lives in payment_ops.py.
"""
import base64
import hashlib
import hmac
import json
import logging
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen, Request

logger = logging.getLogger(__name__)

CHECKOUT_URL = 'https://www.liqpay.ua/api/3/checkout'
API_URL = 'https://www.liqpay.ua/api/request'


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

    def create_payment_form(self, order_id, amount, description, result_url, server_url):
        params = {
            'version': 3,
            'public_key': self.public_key,
            'action': 'pay',
            'amount': str(float(amount)),
            'currency': 'UAH',
            'description': description,
            'order_id': order_id,
            'result_url': result_url,
            'server_url': server_url,
            'language': 'uk',
        }
        if self.sandbox:
            params['sandbox'] = 1

        data = self._encode_params(params)
        signature = self._generate_signature(data)
        return data, signature, CHECKOUT_URL

    def api_request(self, params, timeout=10, max_retries=2):
        action = params.get('action', 'unknown')
        data = self._encode_params(params)
        signature = self._generate_signature(data)
        body = urlencode({'data': data, 'signature': signature}).encode('utf-8')

        for attempt in range(max_retries + 1):
            req = Request(API_URL, data=body, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            try:
                with urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read())
            except URLError as e:
                logger.warning(
                    'LiqPay API connection error (attempt %d/%d): action=%s, error=%s',
                    attempt + 1, max_retries + 1, action, e,
                )
            except json.JSONDecodeError as e:
                logger.error('LiqPay API invalid JSON: action=%s, error=%s', action, e)
                return None
            except Exception:
                logger.exception('LiqPay API unexpected error: action=%s', action)
                return None

            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))

        logger.error('LiqPay API failed after %d attempts: action=%s', max_retries + 1, action)
        return None

    def check_status(self, order_id):
        return self.api_request({
            'version': 3,
            'public_key': self.public_key,
            'action': 'status',
            'order_id': order_id,
        })

    def create_refund_request(self, order_id, amount):
        return self.api_request({
            'version': 3,
            'public_key': self.public_key,
            'action': 'refund',
            'order_id': order_id,
            'amount': str(float(amount)),
        })

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
