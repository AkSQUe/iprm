"""HTTP webhook dispatcher для партнерських інтеграцій.

Відправляє HMAC-підписані HTTP POST на партнерський URL. Публічний
контракт:
    POST <partner_webhook_url>
    Headers:
        Content-Type: application/json; charset=utf-8
        X-IPRM-Signature: HMAC-SHA256(body, partner_webhook_secret) hex
        X-IPRM-Event-Id: event_uuid (партнер дедуплікує по ньому -- **stable**
                                     між повторними спробами)
        User-Agent: iprm-webhook/1.0

    Body:
        {
            "event_type": "event.updated" | "event.deleted" | "event.created",
            "slug": "plazmoterapiya-v-ortopedii",
            "event_id": 3,
            "timestamp": "2026-04-17T14:38:00+00:00"
        }

Payload schema збережена з часів Event-моделі (field `event_id` містить
Course.id). Будь-яка зміна Course АБО CourseInstance тригерить
webhook `event.updated`.

Dispatch сам по собі НЕ робить retry -- викликач (scheduler job, що
обробляє чергу WebhookDelivery) керує повторами з exponential backoff.
"""
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

TIMEOUT = (3.0, 10.0)  # (connect, read)


@dataclass
class DispatchResult:
    """Результат спроби відправки. Use-cases:

    * ok=True: партнер відповів 2xx; permanent success
    * ok=False + retryable=True: transient (5xx, timeout, conn error);
      caller планує retry
    * ok=False + retryable=False: permanent fail (4xx у партнера, неправильний
      URL, etc.); caller ставить final 'failed'
    """
    ok: bool
    retryable: bool
    http_status: int | None
    error: str | None


def _build_payload(course_id, course_slug, action, event_uuid):
    payload = {
        'event_type': f'event.{action}',
        'slug': course_slug,
        'event_id': course_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    return body, event_uuid


def _sign(body_str, secret):
    return hmac.new(
        secret.encode('utf-8'),
        body_str.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def dispatch_one(course_id, course_slug, action, target_url, secret, event_uuid):
    """Одна спроба відправки. Повертає DispatchResult.

    НЕ робить retry самостійно; НЕ пише в DB. Caller (process_webhook_queue)
    оновлює WebhookDelivery стан згідно результату.
    """
    # Фаза 1: зібрати payload + підпис.
    try:
        body, _ = _build_payload(course_id, course_slug, action, event_uuid)
        signature = _sign(body, secret)
    except Exception as exc:  # noqa: BLE001 -- кеш для будь-якого збою
        logger.exception(
            'Webhook build error course=%s action=%s: %s',
            course_id, action, exc,
        )
        return DispatchResult(ok=False, retryable=False, http_status=None, error=str(exc)[:500])

    # Фаза 2: HTTP POST.
    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'X-IPRM-Signature': signature,
        'X-IPRM-Event-Id': event_uuid,
        'User-Agent': 'iprm-webhook/1.0',
    }
    try:
        response = requests.post(
            target_url,
            data=body.encode('utf-8'),
            headers=headers,
            timeout=TIMEOUT,
        )
    except requests.Timeout as exc:
        return DispatchResult(
            ok=False, retryable=True, http_status=None,
            error=f'timeout: {exc}',
        )
    except requests.ConnectionError as exc:
        return DispatchResult(
            ok=False, retryable=True, http_status=None,
            error=f'connection error: {exc}',
        )
    except requests.RequestException as exc:
        return DispatchResult(
            ok=False, retryable=False, http_status=None,
            error=f'request error: {exc}',
        )

    # Фаза 3: обробка статусу.
    if response.ok:
        return DispatchResult(
            ok=True, retryable=False, http_status=response.status_code, error=None,
        )
    # 5xx retryable, 4xx -- ні (партнер відхилив остаточно).
    retryable = response.status_code >= 500
    return DispatchResult(
        ok=False,
        retryable=retryable,
        http_status=response.status_code,
        error=(response.text or '')[:500],
    )
