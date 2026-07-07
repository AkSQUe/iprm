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
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

TIMEOUT = (3.0, 10.0)  # (connect, read)
_USER_AGENT = 'iprm-mm-medic/1.0'
_API_PREFIX = '/api/partner/iprm'
_MAX_ATTEMPTS = 3          # 1 initial + 2 retries on transient failures
_RETRY_BACKOFF = 0.4       # seconds, multiplied by attempt index


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
        """Signed request with inline retry on transient failures.

        A stable X-IPRM-Request-Id keeps the retry idempotent server-side, so a
        write that timed out mid-flight is not applied twice. Retries: timeouts,
        connection errors and 5xx. 4xx are permanent (returned immediately).
        """
        url = f'{self.base_url}{_API_PREFIX}{path}'
        if payload is None:
            body_bytes = b''
        else:
            body_bytes = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        # Stable across retries so idempotency keys match.
        request_id = request_id or uuid.uuid4().hex

        last = MMResult(ok=False, error='Не вдалося виконати запит')
        for attempt in range(_MAX_ATTEMPTS):
            timestamp = str(int(time.time()))
            headers = {
                'X-IPRM-Signature': _sign(timestamp, body_bytes, self.secret),
                'X-IPRM-Timestamp': timestamp,
                'User-Agent': _USER_AGENT,
                'X-IPRM-Request-Id': request_id,
            }
            if payload is not None:
                headers['Content-Type'] = 'application/json; charset=utf-8'

            try:
                response = requests.request(
                    method, url, data=body_bytes if payload is not None else None,
                    headers=headers, timeout=TIMEOUT,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = MMResult(ok=False, error=f'Немає зв’язку з MM Medic: {exc}')
                self._backoff(attempt)
                continue
            except requests.RequestException as exc:
                return MMResult(ok=False, error=f'Помилка запиту: {exc}')

            try:
                data = response.json()
            except ValueError:
                data = None

            if response.ok:
                return MMResult(ok=True, http_status=response.status_code, data=data)

            if response.status_code >= 500:
                last = MMResult(ok=False, http_status=response.status_code,
                                error=f'MM Medic {response.status_code}')
                self._backoff(attempt)
                continue

            # 4xx -- permanent, return structured error.
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

        return last

    @staticmethod
    def _backoff(attempt: int) -> None:
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_RETRY_BACKOFF * (attempt + 1))

    # ---- public API ----
    def fetch_catalog(self, consumable: bool = False, search: str = None) -> MMResult:
        params = {}
        if consumable:
            params['consumable'] = '1'
        if search:
            params['search'] = search
        path = '/catalog'
        if params:
            path = f'{path}?{urlencode(params)}'
        return self._request('GET', path)

    def fetch_templates(self) -> MMResult:
        return self._request('GET', '/templates')

    def adjust_reservation(self, external_ref: str, items: list,
                           request_id: Optional[str] = None) -> MMResult:
        return self._request('POST', f'/reservations/{external_ref}/adjust',
                             {'items': items}, request_id=request_id or uuid.uuid4().hex)

    def create_reservation(self, external_ref: str, event_meta: dict,
                           items: list, partial: bool = False,
                           replace: bool = False) -> MMResult:
        payload = {
            'external_ref': external_ref,
            'items': items,
            'partial': partial,
            'replace': replace,
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
