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
from decimal import Decimal, InvalidOperation

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
# ОДИН словник на весь проєкт, узятий із сервісу. Спершу тут лежала власна
# копія з тим самим вмістом -- і це рівно те, від чого застерігав її ж
# коментар: два літеральні словники на одну відповідність розходяться на
# першому новому значенні. Приймач і звірка мусять читати той самий стан
# партнера однаково, інакше локальний статус залежить від того, хто його
# побачив першим.
_STATUS_MAP = mrs.REMOTE_TO_LOCAL

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


def _as_decimal(value):
    """Coerce a payload money value to Decimal; None stays None ('not reported').

    Через рядок, а не через float: `Decimal(0.1)` дає 0.1000000000000000055,
    і після кількох додавань у звіті з'являються копійки нізвідки.
    """
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
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
            if not isinstance(raw, dict):
                continue
            sku = raw.get('sku')
            if sku is None:
                continue
            # ТИП, а не лише довжина. Спершу тут стояло `len(str(sku))`, тобто
            # міряло стрінгіфіковану форму, а нижче в ключ словника й у колонку
            # йшов СИРИЙ об'єкт: `{"sku": ["A"]}` давало
            # `TypeError: unhashable type` -- неспійманий 500 і втрачений штовх,
            # а `{"sku": 12345}` доходило до PostgreSQL і падало на commit.
            if not isinstance(sku, str):
                return 'sku_not_a_string'
            if len(sku) > 100:
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


def _apply_items(reservation, items, local_status, has_items_key):
    """Write the five per-line quantities from the payload onto the mirror.

    Handles both payload shapes: the legacy one carries a single ``quantity``,
    the new one carries the four lifecycle quantities.

    ЗМІСТ ``quantity`` ЗАЛЕЖИТЬ ВІД СТАТУСУ, і це не наша примха. MM Medic на
    ``consumed`` перезаписує кількість рядка фактично спожитою
    (``partner_event_reservation_service.submit_actuals``), тож у термінальному
    штовху те саме поле означає «використано», а не «погоджено». Приймати його
    як погоджене означало б стерти в дзеркалі цифру, на якій тримаються
    пікінг-лист і звіт «зарезервовано проти спожитого».

    ``local_status``, а не сирий рядок: спершу тут стояв власний список
    (``'consumed', 'completed'``), і це відтворювало ту саму регресію на один
    статус далі -- перший новий термінальний статус партнера в список не
    потрапив би, ``quantity`` знову ліг би в ``quantity_reserved``. Джерело
    істини одне -- мапа статусів.

    ``has_items_key`` розрізняє «рядків НЕ НАДІСЛАНО» і «надіслано порожній
    список». Це різні твердження, і плутати їх дорого: рядок зникає з
    термінального payload рівно тоді, коли повернули все, але status-only штовх
    (``{"external_ref": …, "status": "completed"}``) не говорить про рядки
    НІЧОГО. Доки обидва випадки зводились до ``[]``, легкий штовх стирав
    фактику по всьому документу.
    """
    if not isinstance(items, list):
        return False

    terminal = local_status == MaterialReservationStatus.CONSUMED

    by_sku = {}
    for raw in items:
        if isinstance(raw, dict) and raw.get('sku'):
            by_sku[raw['sku']] = raw
    if not by_sku and not (terminal and has_items_key):
        return False

    changed = False
    existing = {item.sku: item for item in reservation.items}

    if terminal and has_items_key:
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

        # Гроші за видане. Відсутнє поле означає «не повідомили» (старий
        # MM Medic), і тоді вже відоме значення лишається; явний null означає
        # «оцінити нічим», і тоді `cost_complete` теж мусить бути NULL, а не
        # `false` -- інакше документ до відвантаження виглядав би як такий, у
        # якого собівартість порахована неповно.
        if 'cost_uah' in raw:
            cost = _as_decimal(raw.get('cost_uah'))
            fields['cost_uah'] = cost
            fields['cost_complete'] = (
                bool(raw.get('cost_complete')) if cost is not None else None
            )

        # Consumed = issued minus returned. Fall back to the legacy behaviour
        # (a `consumed` push whose `quantity` IS the used amount) so an older
        # MM Medic build keeps working until it ships the new payload.
        effective_issued = fields['quantity_issued']
        if effective_issued is not None:
            fields['quantity_actual'] = effective_issued - (fields['quantity_returned'] or 0)
        elif terminal and legacy_qty is not None:
            fields['quantity_actual'] = legacy_qty

        if local_status == MaterialReservationStatus.RESERVED:
            # Документ повернувся в резерв -- MM Medic скасував помилкове
            # списання (`revert_consumption` з target=active). Фактичних
            # кількостей у зарезервованого документа за визначенням немає, а
            # лишені старі показували б у пікінг-листі й у звіті
            # «зарезервовано проти спожитого» витрату по документу, який нічого
            # не спожив. Жоден інший штовх сюди не потрапляє з непорожнім
            # `quantity_actual`: у резерв документ інакше не повертається.
            fields['quantity_actual'] = None

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

    if local_status is None:
        # Невідомий статус -- НІЧОГО не застосовуємо: ні статус, ні кількості,
        # ні номер документа, ні мітку часу.
        #
        # Раніше тут лишався лише лог, а виконання йшло далі: `_apply_items` з
        # `terminal=False` брав legacy `quantity` як ПОГОДЖЕНЕ й писав його в
        # `quantity_reserved`, мітка просувалась, і дзеркало опинялось у
        # змішаному стані -- усе, крім статусу, від штовха, який ми відмовились
        # зрозуміти. Плюс просунута мітка відсікала наступний, справді
        # легітимний штовх як застарілий.
        logger.warning('MM Medic status webhook: unknown status %r for ref=%s, '
                       'nothing applied', remote_status, external_ref)
        return jsonify({'status': 'unknown_status',
                        'reservation_status': reservation.status}), 200

    changed = created
    status_changed = reservation.status != local_status
    if status_changed:
        reservation.status = local_status
        changed = True

    document_number = _trim(payload.get('document_number'), 50)
    if document_number and reservation.document_number != document_number:
        reservation.document_number = document_number
        changed = True

    raw_items = payload.get('items')
    if _apply_items(reservation, raw_items or [], local_status,
                    isinstance(raw_items, list)):
        changed = True
        stock_changed = True
    else:
        stock_changed = False

    if local_status == MaterialReservationStatus.CONSUMED and not reservation.consumed_at:
        reservation.consumed_at = datetime.now(timezone.utc)
        changed = True
        stock_changed = True
    elif (local_status == MaterialReservationStatus.RESERVED
            and reservation.consumed_at):
        # Списання скасували на боці MM Medic -- дата списання більше ні до
        # чого не належить. Лишена, вона робить документ «списаним» для всього,
        # що дивиться на `consumed_at`, а не на статус.
        reservation.consumed_at = None
        changed = True
        stock_changed = True

    # Мітку просуваємо НЕЗАЛЕЖНО від `changed`: штовх, який нічого не змінив,
    # усе одно є свіжішим знімком стану. Доки це стояло всередині `if changed`,
    # наступний, справді старіший штовх проходив як «свіжий».
    if remote_updated_at and remote_updated_at != stored_updated_at:
        reservation.remote_updated_at = remote_updated_at
        changed = True

    if changed:
        reservation.last_response = payload
        db.session.commit()
        # Кеш каталогу чистимо лише коли змінились СТАТУС або РЯДКИ: саме вони
        # впливають на доступність товару. Рух самої лише мітки часу цього не
        # робить, а при 120 штовхах/хв безумовна інвалідація не давала
        # 45-секундному кешу прожити жодного разу.
        if stock_changed or status_changed or created:
            mrs.invalidate_catalog_cache()
        logger.info('MM Medic status webhook %s ref=%s -> %s',
                    'created' if created else 'applied',
                    external_ref, reservation.status)

    return jsonify({
        'status': 'created' if created else 'ok',
        'reservation_status': reservation.status,
    }), 200
