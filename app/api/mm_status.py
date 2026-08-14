"""Inbound receiver for MM Medic -> IPRM reservation status webhooks.

MM Medic pushes a reservation's current state whenever it changes. Two kinds of
change arrive here:

  * changes to a request IPRM itself started (approval, issue, expiry, manual
    release by warehouse staff) -- we update the local mirror;
  * a request that was BORN on MM Medic, submitted by a trainer in its admin.
    IPRM has never seen that external_ref, so the row is created here. Without
    this the trainer's materials page and /admin/materials would simply never
    show it -- the reconcile job only ever revisits refs it already knows.

Auth mirrors the partner API: HMAC-SHA256(secret, "<timestamp>.<raw_body>") with
the shared partner_webhook_secret + X-IPRM-Timestamp (replay window 300s).
"""
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.extensions import db, csrf, limiter
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation,
    MaterialReservationItem,
    MaterialReservationOrigin,
    MaterialReservationStatus,
)
from app.models.site_settings import SiteSettings
from app.services import material_reservation_service as mrs

logger = logging.getLogger(__name__)

mm_status_bp = Blueprint('mm_status', __name__, url_prefix='/api/partner/mm-medic')

_SKEW_SECONDS = 300

# MM Medic reservation/header status -> local MaterialReservationStatus.
#
# 'active' (legacy) and 'approved' (new) both land on RESERVED: both mean the
# hold exists. Keeping them on one local value is what lets the six
# `status == RESERVED` gates in admin/routes_materials.py stay correct.
# 'consumed' (legacy) and 'completed' (new) likewise share CONSUMED.
_STATUS_MAP = {
    'submitted': MaterialReservationStatus.SUBMITTED,
    'active': MaterialReservationStatus.RESERVED,
    'approved': MaterialReservationStatus.RESERVED,
    'issued': MaterialReservationStatus.ISSUED,
    'consumed': MaterialReservationStatus.CONSUMED,
    'completed': MaterialReservationStatus.CONSUMED,
    'rejected': MaterialReservationStatus.REJECTED,
    'cancelled': MaterialReservationStatus.CANCELLED,
    'released': MaterialReservationStatus.CANCELLED,
    'expired': MaterialReservationStatus.EXPIRED,
}

# Statuses that carry nothing worth filing if we have never heard of the ref:
# there is no history to preserve and no action left to take.
_NO_CREATE_STATUSES = (
    MaterialReservationStatus.CANCELLED,
    MaterialReservationStatus.EXPIRED,
)


def _as_utc(value):
    """Force a datetime to aware UTC. SQLite hands DateTime(timezone=True) back
    NAIVE, so a stored value and a freshly parsed one are not comparable without
    this -- the mismatch raises TypeError and turns the webhook into a 500."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_dt(raw):
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or None."""
    if not raw:
        return None
    try:
        return _as_utc(datetime.fromisoformat(str(raw).replace('Z', '+00:00')))
    except (TypeError, ValueError):
        return None


def _as_int(value):
    """Coerce a payload number to int; None stays None (means 'not reported')."""
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _trim(value, length):
    """Обрізати ОПИСОВЕ поле під довжину колонки.

    SQLite мовчки пише будь-яку довжину, PostgreSQL кидає
    StringDataRightTruncation — тобто без цього тести зелені, а прод віддає
    500 і губить штовх (ретраїв у відправника немає).

    Обрізаємо мовчки саме описові поля: зіпсована назва товару гірша за
    відсутню, але не ламає звʼязків. Ідентифікатори натомість відхиляються
    (`_payload_error`): обрізаний ідентифікатор -- це ІНШИЙ рядок.
    """
    if value is None:
        return None
    text = str(value)
    return text[:length] if len(text) > length else text


def _payload_error(payload, external_ref):
    """Перевірити ідентифікуючі поля. Повертає код помилки або None."""
    if len(external_ref) > 64:
        return 'ref_too_long'
    items = payload.get('items')
    if isinstance(items, list):
        for raw in items:
            if isinstance(raw, dict) and len(str(raw.get('sku') or '')) > 100:
                return 'sku_too_long'
    return None


def _origin(value):
    """Походження з payload, звірене з білим списком.

    Поле впливає лише на формулювання в інтерфейсі, тож невідоме значення --
    привід відкотитись до дефолта, а не відмовити у прийомі документа.
    """
    if value in MaterialReservationOrigin.ALL:
        return value
    return MaterialReservationOrigin.TRAINER


#: Статуси, після яких резерв закритий: у payload лежать ФАКТИЧНІ кількості.
_TERMINAL_STATUSES = ('consumed', 'completed')


def _apply_items(reservation, items, remote_status):
    """Write the five per-line quantities from the payload onto the mirror.

    Handles both payload shapes: the legacy one carries a single ``quantity``,
    the new one carries the four lifecycle quantities.

    ЗМІСТ ``quantity`` ЗАЛЕЖИТЬ ВІД СТАТУСУ, і це не наша примха. MM Medic на
    ``consumed`` перезаписує кількість рядка фактично спожитою
    (``partner_event_reservation_service.submit_actuals``), тож у термінальному
    штовху те саме поле означає «використано», а не «погоджено». Приймати його
    як погоджене означало б стерти в дзеркалі цифру, на якій тримаються
    пікінг-лист і звіт «зарезервовано проти спожитого».

    Рядки, ВІДСУТНІ в payload, звичайно не чіпаються: частковий штовх не має
    виглядати як «усе обнулилось». Виняток — термінальний штовх: там рядок
    зникає з payload рівно тоді, коли повернули все (MM Medic звільняє утримання
    з нульовим фактом), і лишити його «зарезервованим» назавжди -- гірше.
    """
    if not isinstance(items, list):
        return False

    terminal = remote_status in _TERMINAL_STATUSES

    by_sku = {}
    for raw in items:
        if isinstance(raw, dict) and raw.get('sku'):
            by_sku[raw['sku']] = raw
    if not by_sku and not terminal:
        return False

    changed = False
    existing = {item.sku: item for item in reservation.items}

    if terminal:
        for sku, item in existing.items():
            if sku not in by_sku and item.quantity_actual != 0:
                item.quantity_actual = 0
                item.quantity_returned = item.quantity_reserved
                changed = True

    for sku, raw in by_sku.items():
        item = existing.get(sku)
        if item is None:
            item = MaterialReservationItem(sku=sku, quantity_reserved=0)
            reservation.items.append(item)
            existing[sku] = item
            changed = True

        legacy_qty = _as_int(raw.get('quantity'))
        requested = _as_int(raw.get('quantity_requested'))
        approved = _as_int(raw.get('quantity_approved'))
        issued = _as_int(raw.get('quantity_issued'))
        returned = _as_int(raw.get('quantity_returned'))

        # Legacy payload: `quantity` -- це погоджене, але ЛИШЕ поки резерв
        # живий. У термінальному штовху воно вже означає спожите (див.
        # докстрінг), тож погодженого в такому payload немає взагалі, і
        # чіпати `quantity_reserved` не можна.
        if approved is None and not terminal:
            approved = legacy_qty

        fields = {
            'name': _trim(raw.get('name'), 255) or item.name,
            'image_url': _trim(raw.get('image') or raw.get('image_url'),
                               500) or item.image_url,
            'quantity_requested': requested if requested is not None else item.quantity_requested,
            'quantity_issued': issued if issued is not None else item.quantity_issued,
            'quantity_returned': returned if returned is not None else item.quantity_returned,
        }
        if approved is not None:
            fields['quantity_reserved'] = approved

        # Consumed = issued minus returned. Fall back to the legacy behaviour
        # (a `consumed` push whose `quantity` IS the used amount) so an older
        # MM Medic build keeps working until it ships the new payload.
        effective_issued = fields['quantity_issued']
        if effective_issued is not None:
            fields['quantity_actual'] = effective_issued - (fields['quantity_returned'] or 0)
        elif terminal and legacy_qty is not None:
            fields['quantity_actual'] = legacy_qty

        for attr, value in fields.items():
            if getattr(item, attr) != value:
                setattr(item, attr, value)
                changed = True

    return changed


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

    invalid = _payload_error(payload, external_ref)
    if invalid:
        return jsonify({'status': invalid}), 400

    local_status = _STATUS_MAP.get(remote_status)
    reservation = MaterialReservation.query.filter_by(external_ref=external_ref).first()
    created = False

    if reservation is None:
        # A request born on MM Medic. Recover the захід from the ref and file it.
        #
        # Кожна відмова тут ЛОГУЄТЬСЯ. Ці гілки віддають 200 (щоб відправник не
        # довбав безнадійний штовх), тобто зовні вони не відрізняються від
        # успіху -- а означають втрачений документ. Доти успіх писався в лог,
        # а втрата мовчала.
        if local_status is None or local_status in _NO_CREATE_STATUSES:
            logger.warning(
                'MM Medic status webhook dropped: ref=%s status=%r not creatable',
                external_ref, remote_status)
            return jsonify({'status': 'unknown_ref'}), 200
        instance_id = mrs.instance_id_from_ref(external_ref)
        if instance_id is None:
            logger.warning('MM Medic status webhook dropped: ref=%s is not ours',
                           external_ref)
            return jsonify({'status': 'unknown_ref'}), 200
        if not db.session.get(CourseInstance, instance_id):
            # The захід does not exist here (deleted, or a ref from another
            # environment). Ack so MM Medic stops retrying a hopeless push.
            logger.warning('MM Medic status webhook for unknown instance %s (ref=%s)',
                           instance_id, external_ref)
            return jsonify({'status': 'unknown_instance'}), 200
        reservation = MaterialReservation(
            instance_id=instance_id,
            external_ref=external_ref,
            status=local_status,
            origin=_origin(payload.get('origin')),
            sent_at=datetime.now(timezone.utc),
        )
        # Вставку робимо ОКРЕМИМ flush, до того як у сесію потраплять рядки.
        # `external_ref` унікальний, тож два одночасні штовхи на той самий
        # новий ref дали б IntegrityError на спільному commit -- 500 і
        # назавжди втрачений штовх, бо ретраїв у відправника немає. Тут же
        # програвший просто перечитує переможця й працює далі.
        #
        # `rollback()` безпечний саме через порядок: у цій точці запиту сесія
        # містить лише цю вставку, тож відкочувати більше нічого. SAVEPOINT
        # був би акуратніший, але pysqlite ламає вкладені транзакції, і тести
        # почали б брехати в обидва боки.
        db.session.add(reservation)
        try:
            db.session.flush()
            created = True
        except IntegrityError:
            db.session.rollback()
            reservation = MaterialReservation.query.filter_by(
                external_ref=external_ref).first()
            if reservation is None:
                raise
            logger.info('MM Medic status webhook lost the create race ref=%s',
                        external_ref)

    remote_updated_at = _parse_dt(payload.get('updated_at'))
    stored_updated_at = _as_utc(reservation.remote_updated_at)
    if (not created and remote_updated_at and stored_updated_at
            and remote_updated_at < stored_updated_at):
        # Pushes are posted off-thread on MM Medic and can overtake each other.
        # An older snapshot must never undo a newer one.
        logger.info('MM Medic status webhook out of order ref=%s (%s < %s)',
                    external_ref, remote_updated_at, stored_updated_at)
        return jsonify({'status': 'stale_push',
                        'reservation_status': reservation.status}), 200

    changed = created
    if local_status is None:
        # Невідомий статус: рядок лишається як був. Без логу це виглядало б як
        # успішно застосований штовх.
        logger.warning('MM Medic status webhook: unknown status %r for ref=%s',
                       remote_status, external_ref)
    elif reservation.status != local_status:
        reservation.status = local_status
        changed = True

    document_number = _trim(payload.get('document_number'), 50)
    if document_number and reservation.document_number != document_number:
        reservation.document_number = document_number
        changed = True

    if _apply_items(reservation, payload.get('items') or [], remote_status):
        changed = True

    if local_status == MaterialReservationStatus.CONSUMED and not reservation.consumed_at:
        reservation.consumed_at = datetime.now(timezone.utc)
        changed = True

    # Мітку просуваємо НЕЗАЛЕЖНО від `changed`: штовх, який нічого не змінив,
    # усе одно є свіжішим знімком стану. Доки це стояло всередині `if changed`,
    # наступний, справді старіший штовх проходив як «свіжий».
    if remote_updated_at and remote_updated_at != stored_updated_at:
        reservation.remote_updated_at = remote_updated_at
        changed = True

    if changed:
        reservation.last_response = payload
        db.session.commit()
        mrs.invalidate_catalog_cache()
        logger.info('MM Medic status webhook %s ref=%s -> %s',
                    'created' if created else 'applied',
                    external_ref, reservation.status)

    return jsonify({
        'status': 'created' if created else 'ok',
        'reservation_status': reservation.status,
    }), 200
