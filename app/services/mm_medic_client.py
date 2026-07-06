"""Outgoing request/response client for the MM Medic partner reservation API.

Signs every request with HMAC-SHA256 over "<timestamp>.<raw_body>" using the shared
partner_webhook_secret (the same secret MM Medic verifies as iprm_webhook_secret).
Mirrors app.services.webhook_dispatcher._sign but adds the timestamp so the empty-body
GET /catalog is replay-resistant.

Config comes from SiteSettings: mm_medic_integration_enabled, mm_medic_api_base_url,
partner_webhook_secret. All methods return a MMResult so the admin UI can render
success/shortfalls/errors without catching exceptions.
"""
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

TIMEOUT = (3.0, 10.0)  # (connect, read)
_USER_AGENT = 'iprm-mm-medic/1.0'
_API_PREFIX = '/api/partner/iprm'


@dataclass
class MMResult:
    ok: bool
    http_status: Optional[int] = None
    data: Any = None
    error: Optional[str] = None
    shortfalls: list = field(default_factory=list)


class MMConfigError(Exception):
    """Integration disabled or misconfigured (URL/secret missing)."""


def _sign(timestamp: str, body_bytes: bytes, secret: str) -> str:
    signed = timestamp.encode('utf-8') + b'.' + body_bytes
    return hmac.new(secret.encode('utf-8'), signed, hashlib.sha256).hexdigest()


class MMMedicClient:
    """Thin signed HTTP client for MM Medic partner reservation endpoints."""

    def __init__(self, base_url: str, secret: str):
        self.base_url = (base_url or '').rstrip('/')
        self.secret = secret

    # ---- construction from settings ----
    @classmethod
    def from_settings(cls, site_settings) -> 'MMMedicClient':
        if not getattr(site_settings, 'mm_medic_integration_enabled', False):
            raise MMConfigError('Інтеграцію з MM Medic вимкнено')
        base_url = (site_settings.mm_medic_api_base_url or '').strip()
        secret = (site_settings.partner_webhook_secret or '').strip()
        if not base_url:
            raise MMConfigError('Не вказано базовий URL API MM Medic')
        if not secret:
            raise MMConfigError('Не налаштовано спільний секрет (partner_webhook_secret)')
        return cls(base_url, secret)

    # ---- transport ----
    def _request(self, method: str, path: str, payload: Optional[dict] = None,
                 request_id: Optional[str] = None) -> MMResult:
        url = f'{self.base_url}{_API_PREFIX}{path}'
        if payload is None:
            body_bytes = b''
        else:
            body_bytes = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        timestamp = str(int(time.time()))
        headers = {
            'X-IPRM-Signature': _sign(timestamp, body_bytes, self.secret),
            'X-IPRM-Timestamp': timestamp,
            'User-Agent': _USER_AGENT,
        }
        if payload is not None:
            headers['Content-Type'] = 'application/json; charset=utf-8'
        if request_id:
            headers['X-IPRM-Request-Id'] = request_id

        try:
            response = requests.request(
                method, url, data=body_bytes if payload is not None else None,
                headers=headers, timeout=TIMEOUT,
            )
        except requests.Timeout as exc:
            return MMResult(ok=False, error=f'Тайм-аут з’єднання з MM Medic: {exc}')
        except requests.ConnectionError as exc:
            return MMResult(ok=False, error=f'Немає з’єднання з MM Medic: {exc}')
        except requests.RequestException as exc:
            return MMResult(ok=False, error=f'Помилка запиту: {exc}')

        try:
            data = response.json()
        except ValueError:
            data = None

        if response.ok:
            return MMResult(ok=True, http_status=response.status_code, data=data)

        # Structured error paths
        shortfalls = (data or {}).get('shortfalls') if isinstance(data, dict) else None
        err = None
        if isinstance(data, dict):
            err = data.get('error') or data.get('status')
        return MMResult(
            ok=False,
            http_status=response.status_code,
            data=data,
            error=err or (response.text or '')[:300],
            shortfalls=shortfalls or [],
        )

    # ---- public API ----
    def fetch_catalog(self) -> MMResult:
        return self._request('GET', '/catalog')

    def create_reservation(self, external_ref: str, event_meta: dict,
                           items: list, partial: bool = False) -> MMResult:
        payload = {
            'external_ref': external_ref,
            'items': items,
            'partial': partial,
            **{k: v for k, v in event_meta.items() if v is not None},
        }
        return self._request('POST', '/reservations', payload,
                             request_id=uuid.uuid4().hex)

    def get_reservation(self, external_ref: str) -> MMResult:
        return self._request('GET', f'/reservations/{external_ref}')

    def update_actuals(self, external_ref: str, items: list,
                       request_id: Optional[str] = None) -> MMResult:
        payload = {'items': items}
        return self._request('POST', f'/reservations/{external_ref}/actuals',
                             payload, request_id=request_id or uuid.uuid4().hex)

    def cancel_reservation(self, external_ref: str,
                           request_id: Optional[str] = None) -> MMResult:
        return self._request('POST', f'/reservations/{external_ref}/cancel',
                             {}, request_id=request_id or uuid.uuid4().hex)
