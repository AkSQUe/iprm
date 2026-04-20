"""HTTP webhook dispatcher — notifies partner sites on Course changes.

Fire-and-forget: failures are logged but never bubble up to the caller. Pull
beat on the partner side acts as safety net if a webhook is lost.

Payload schema (схема збережена з часів Event-моделі для сумісності з
партнерськими споживачами; `event_id` тепер містить Course.id):
    {
        "event_type": "event.updated" | "event.deleted" | "event.created",
        "slug": "plazmoterapiya-v-ortopedii",
        "event_id": 3,
        "timestamp": "2026-04-17T14:38:00+00:00"
    }

Будь-яка зміна Course АБО CourseInstance тригерить webhook `event.updated`
на курс (щоб партнер оновив і контент, і розклад через /api/v1/events/<slug>).

Headers:
    X-IPRM-Signature: HMAC-SHA256(body, partner_webhook_secret) in hex
    X-IPRM-Event-Id: UUID4 (partner deduplicates on this)
    Content-Type: application/json
"""
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

TIMEOUT = (3.0, 10.0)  # (connect, read)


def dispatch_event_webhook(event_id: int, event_slug: str, action: str) -> None:
    """Fire a webhook for Event {created,updated,deleted}.

    Args:
        event_id: Event.id at commit time. For deletes, provided before row is gone.
        event_slug: Event.slug snapshot (deleted rows still need this in payload).
        action: 'created' | 'updated' | 'deleted'.

    Safe to call from anywhere — all exceptions are caught and logged.
    Returns nothing; caller has no way to tell if the POST succeeded.
    """
    try:
        from app.models.site_settings import SiteSettings
        settings = SiteSettings.get()

        if not settings.partner_webhook_enabled:
            return
        url = (settings.partner_webhook_url or '').strip()
        secret = settings.partner_webhook_secret
        if not url or not secret:
            logger.warning(
                'partner_webhook_enabled=True but url/secret missing — skipping'
            )
            return

        payload = {
            'event_type': f'event.{action}',
            'slug': event_slug,
            'event_id': event_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)

        signature = hmac.new(
            secret.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'X-IPRM-Signature': signature,
            'X-IPRM-Event-Id': uuid.uuid4().hex,
            'User-Agent': 'iprm-webhook/1.0',
        }

        response = requests.post(
            url,
            data=body.encode('utf-8'),
            headers=headers,
            timeout=TIMEOUT,
        )
        if response.ok:
            logger.info(
                'Webhook delivered: %s event_id=%s status=%d',
                action, event_id, response.status_code,
            )
        else:
            # Not fatal — pull beat will catch up within 30 min.
            logger.warning(
                'Webhook non-2xx response: %s event_id=%s status=%d body=%s',
                action, event_id, response.status_code, response.text[:200],
            )
    except requests.RequestException as exc:
        logger.warning(
            'Webhook HTTP error: %s event_id=%s err=%s',
            action, event_id, exc,
        )
    except Exception as exc:
        # Absolutely never raise from here — Event commit must succeed
        # regardless of downstream partner availability.
        logger.exception(
            'Webhook dispatcher crashed for %s event_id=%s: %s',
            action, event_id, exc,
        )
