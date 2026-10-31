"""Перевірка підписаного запиту від MM Medic.

Спільна для всіх вхідних партнерських ендпоінтів: HMAC-SHA256 від
"<timestamp>.<raw_body>" спільним секретом partner_webhook_secret, заголовки
X-IPRM-Signature та X-IPRM-Timestamp, вікно повтору 300 с. Одна реалізація
на всі приймачі: два приймачі з власною копією перевірки розходяться на
першій же правці.
"""
import hashlib
import hmac
import time

from flask import jsonify, request

from app.models.site_settings import SiteSettings

SKEW_SECONDS = 300


def _reject(status, code):
    return None, (jsonify({'status': status}), code)


def verify_signed_request():
    """Перевірити інтеграцію, підпис і тіло запиту.

    Повертає (payload, None) або (None, (відповідь, код)).
    """
    site = SiteSettings.get()
    if not site.mm_medic_integration_enabled:
        return _reject('disabled', 404)
    secret = (site.partner_webhook_secret or '').strip()
    if not secret:
        return _reject('misconfigured', 503)

    sig = request.headers.get('X-IPRM-Signature', '')
    ts = request.headers.get('X-IPRM-Timestamp', '')
    if not sig or not ts:
        return _reject('missing_headers', 400)
    try:
        skew = abs(time.time() - int(ts))
    except (TypeError, ValueError):
        return _reject('bad_timestamp', 400)
    if skew > SKEW_SECONDS:
        return _reject('stale', 401)

    body = request.get_data()
    expected = hmac.new(secret.encode('utf-8'), ts.encode('utf-8') + b'.' + body,
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return _reject('invalid_signature', 401)

    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict):
        return _reject('malformed', 400)
    return payload, None
