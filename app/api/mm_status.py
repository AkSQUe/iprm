"""Inbound receiver for MM Medic -> IPRM reservation status webhooks.

MM Medic pushes a reservation's current state when it changes outside the partner
API flow (hold expiry, manual release/consume by warehouse staff). IPRM updates
the local MaterialReservation so its status is real-time without waiting for the
30-minute reconcile job.

Auth mirrors the partner API: HMAC-SHA256(secret, "<timestamp>.<raw_body>") with
the shared partner_webhook_secret + X-IPRM-Timestamp (replay window 300s).
"""
import hashlib
import hmac
import logging
import time

from flask import Blueprint, jsonify, request

from app.extensions import db, csrf, limiter
from app.models.material_reservation import MaterialReservation, MaterialReservationStatus
from app.models.site_settings import SiteSettings
from app.services import material_reservation_service as mrs

logger = logging.getLogger(__name__)

mm_status_bp = Blueprint('mm_status', __name__, url_prefix='/api/partner/mm-medic')

_SKEW_SECONDS = 300

# MM Medic reservation/header status -> local MaterialReservationStatus.
_STATUS_MAP = {
    'active': MaterialReservationStatus.RESERVED,
    'consumed': MaterialReservationStatus.CONSUMED,
    'cancelled': MaterialReservationStatus.CANCELLED,
    'expired': MaterialReservationStatus.EXPIRED,
    'released': MaterialReservationStatus.CANCELLED,
}


@mm_status_bp.route('/reservation-status', methods=['POST'])
@csrf.exempt
@limiter.limit('120 per minute')
def reservation_status():
    site = SiteSettings.get()
    if not site.mm_medic_integration_enabled:
        return jsonify({'status': 'disabled'}), 404
    secret = (site.partner_webhook_secret or '').strip()
    if not secret:
        return jsonify({'status': 'misconfigured'}), 503

    sig = request.headers.get('X-IPRM-Signature', '')
    ts = request.headers.get('X-IPRM-Timestamp', '')
    if not sig or not ts:
        return jsonify({'status': 'missing_headers'}), 400
    try:
        skew = abs(time.time() - int(ts))
    except (TypeError, ValueError):
        return jsonify({'status': 'bad_timestamp'}), 400
    if skew > _SKEW_SECONDS:
        return jsonify({'status': 'stale'}), 401

    body = request.get_data()
    expected = hmac.new(secret.encode('utf-8'), ts.encode('utf-8') + b'.' + body,
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({'status': 'invalid_signature'}), 401

    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict):
        return jsonify({'status': 'malformed'}), 400

    external_ref = (payload.get('external_ref') or '').strip()
    remote_status = payload.get('status')
    if not external_ref:
        return jsonify({'status': 'missing_ref'}), 400

    reservation = MaterialReservation.query.filter_by(external_ref=external_ref).first()
    if reservation is None:
        return jsonify({'status': 'unknown_ref'}), 200  # ack; nothing local to update

    local_status = _STATUS_MAP.get(remote_status)
    changed = False
    if local_status and reservation.status != local_status:
        reservation.status = local_status
        changed = True

    # Sync per-line actuals when the event was consumed on MM Medic.
    items = payload.get('items') or []
    if remote_status == 'consumed' and isinstance(items, list):
        actual_map = {it.get('sku'): it.get('quantity')
                      for it in items if isinstance(it, dict) and it.get('sku')}
        for item in reservation.items:
            if item.sku in actual_map:
                item.quantity_actual = actual_map[item.sku]
                changed = True

    if changed:
        reservation.last_response = payload
        db.session.commit()
        mrs.invalidate_catalog_cache()
        logger.info('MM Medic status webhook applied ref=%s -> %s',
                    external_ref, reservation.status)

    return jsonify({'status': 'ok', 'reservation_status': reservation.status}), 200
