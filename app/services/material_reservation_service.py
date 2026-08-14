"""IPRM-side orchestration for MM Medic consumable-material reservations.

Wraps MMMedicClient calls and persists the local MaterialReservation history so
admin routes stay thin. The source of truth for stock is MM Medic; these records
are IPRM's own audit keyed to a CourseInstance.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem, MaterialReservationStatus,
)
from app.models.site_settings import SiteSettings
from app.services.mm_medic_client import MMMedicClient, MMConfigError

logger = logging.getLogger(__name__)

# Short in-process caches: speed the page up and let it degrade gracefully
# (serve the last good copy when MM Medic is unreachable).
_CATALOG_TTL = 45  # seconds
_catalog_cache = {'items': None, 'ts': 0.0}
_TEMPLATES_TTL = 120  # seconds -- templates change rarely
_templates_cache = {'data': None, 'ts': 0.0}


_EXTERNAL_REF_PREFIX = 'iprm-instance-'


def external_ref_for(instance_id) -> str:
    return f'{_EXTERNAL_REF_PREFIX}{instance_id}'


def instance_id_from_ref(external_ref):
    """Inverse of external_ref_for; None when the ref is not one of ours.

    MM Medic now originates requests too (a trainer submits one there), so the
    status webhook can carry a ref we have never seen. Recovering the instance
    from the ref is the only way to file it against the right захід -- which is
    why the format lives in exactly one place, next to its generator.
    """
    ref = (external_ref or '').strip()
    if not ref.startswith(_EXTERNAL_REF_PREFIX):
        return None
    raw = ref[len(_EXTERNAL_REF_PREFIX):]

    # `isdigit()`, а не `int()`: останній приймає більше форм, ніж генератор
    # виробляє. `int('1_0') == 10`, `int(' 10') == 10`, `int('+10') == 10` --
    # тобто `iprm-instance-1_0` вказував би на той самий захід, але зберігся
    # б під ІНШИМ external_ref (унікальність стоїть саме на ньому). Наслідок --
    # два документи на один захід і недетермінований вибір між ними.
    if not raw.isdigit():
        return None
    value = int(raw)

    # Межа BIGINT: більше значення дає psycopg2 NumericValueOutOfRange уже на
    # SELECT, тобто 500 замість охайного «не знаємо такого».
    if value <= 0 or value > 9223372036854775807:
        return None
    return value


def get_client() -> MMMedicClient:
    """Raises MMConfigError if integration disabled/misconfigured."""
    return MMMedicClient.from_settings(SiteSettings.get())


def make_trainer_token(instance_id) -> str:
    """Signed, non-expiring token for a public read-only trainer materials link."""
    from itsdangerous import URLSafeSerializer
    from flask import current_app
    return URLSafeSerializer(current_app.secret_key, salt='materials-trainer').dumps(instance_id)


def load_trainer_token(token):
    """Return the instance_id from a trainer token, or None if invalid."""
    from itsdangerous import URLSafeSerializer, BadData
    from flask import current_app
    try:
        return URLSafeSerializer(current_app.secret_key, salt='materials-trainer').loads(token)
    except BadData:
        return None
    except Exception:
        logger.exception('trainer token load failed')
        return None


def invalidate_catalog_cache():
    """Drop the cached catalog so the next page load reflects fresh availability
    after a reservation mutation (reserve/actuals/adjust/cancel change derived or
    physical stock)."""
    _catalog_cache['items'] = None
    _catalog_cache['ts'] = 0.0


def get_catalog(consumable=False, search=None, force=False):
    """Fetch the MM Medic catalog. Returns (items, error, stale).

    The unfiltered catalog is cached for a short TTL; on MM Medic failure the last
    good cached copy is served with stale=True. Filtered/search queries always go
    live (and still fall back to the full cache on failure).
    """
    cacheable = not consumable and not (search or '').strip()
    now = time.time()
    if (cacheable and not force and _catalog_cache['items'] is not None
            and (now - _catalog_cache['ts']) < _CATALOG_TTL):
        return _catalog_cache['items'], None, False

    try:
        client = get_client()
    except MMConfigError as exc:
        return [], str(exc), False

    result = client.fetch_catalog(consumable=consumable, search=search)
    if result.ok:
        items = (result.data or {}).get('items') or []
        if cacheable:
            _catalog_cache['items'] = items
            _catalog_cache['ts'] = now
        return items, None, False

    # Failure -> serve stale full catalog if we have one.
    if _catalog_cache['items'] is not None:
        return _catalog_cache['items'], (result.error or 'MM Medic недоступний'), True
    return [], (result.error or 'Не вдалося отримати каталог MM Medic'), False


def get_templates(force=False):
    """Fetch material templates (BOM). Returns (templates, error).

    Cached for a short TTL; on MM Medic failure the last good copy is served.
    """
    now = time.time()
    if (not force and _templates_cache['data'] is not None
            and (now - _templates_cache['ts']) < _TEMPLATES_TTL):
        return _templates_cache['data'], None

    try:
        client = get_client()
    except MMConfigError as exc:
        return (_templates_cache['data'] or []), str(exc)

    result = client.fetch_templates()
    if not result.ok:
        if _templates_cache['data'] is not None:
            return _templates_cache['data'], None
        return [], result.error or 'Не вдалося отримати шаблони'

    data = (result.data or {}).get('templates') or []
    _templates_cache['data'] = data
    _templates_cache['ts'] = now
    return data, None


def get_reservation(instance_id):
    return MaterialReservation.query.filter_by(instance_id=instance_id).first()


def _event_meta(instance) -> dict:
    title = getattr(instance, 'effective_title', None)
    if not title and instance.course is not None:
        title = instance.course.title
    return {
        'event_title': title,
        'event_starts_at': instance.start_date.isoformat() if instance.start_date else None,
        'event_ends_at': instance.end_date.isoformat() if instance.end_date else None,
    }


def create_reservation(instance, items, catalog_by_sku, replace=False):
    """Reserve `items` [{sku, quantity}] on MM Medic and persist locally.

    replace=True atomically swaps an active reservation on MM Medic (used by edit).
    Returns (ok, result, reservation).
    """
    client = get_client()
    ref = external_ref_for(instance.id)
    result = client.create_reservation(ref, _event_meta(instance), items, replace=replace)
    if not result.ok:
        return False, result, None

    reservation = get_reservation(instance.id)
    if reservation is None:
        reservation = MaterialReservation(instance_id=instance.id, external_ref=ref)
        db.session.add(reservation)
    reservation.status = MaterialReservationStatus.RESERVED
    reservation.sent_at = datetime.now(timezone.utc)
    reservation.consumed_at = None
    reservation.actuals_reminder_sent_at = None  # fresh cycle -> reminder eligible again
    reservation.last_response = result.data

    # Rebuild the line snapshot from what we sent + catalog identity.
    for existing in list(reservation.items):
        reservation.items.remove(existing)
    db.session.flush()
    for it in items:
        sku = it['sku']
        cat = catalog_by_sku.get(sku, {})
        reservation.items.append(MaterialReservationItem(
            sku=sku,
            name=cat.get('name'),
            image_url=cat.get('image'),
            quantity_reserved=it['quantity'],
        ))
    db.session.commit()
    invalidate_catalog_cache()  # derived availability changed
    # Note: the "materials reserved" notification is sent by MM Medic to its
    # storekeeper (warehouse managers); IPRM does not email the trainer.
    return True, result, reservation


def submit_actuals(instance, actuals, catalog_by_sku=None, request_id=None):
    """actuals: [{sku, actual_qty}]. Writes off stock on MM Medic + updates local.

    SKUs present in `actuals` that were not previously reserved are recorded as new
    local lines (quantity_reserved=0), snapshotting name/image from catalog_by_sku.
    """
    catalog_by_sku = catalog_by_sku or {}
    client = get_client()
    ref = external_ref_for(instance.id)
    result = client.update_actuals(ref, actuals, request_id=request_id)
    if not result.ok:
        return False, result

    reservation = get_reservation(instance.id)
    if reservation is not None:
        reservation.status = MaterialReservationStatus.CONSUMED
        reservation.consumed_at = datetime.now(timezone.utc)
        reservation.last_response = result.data
        actual_map = {a['sku']: a['actual_qty'] for a in actuals}
        existing_skus = {it.sku for it in reservation.items}
        for item in reservation.items:
            item.quantity_actual = actual_map.get(item.sku, item.quantity_reserved)
        # On-the-fly additions -> new local lines.
        for sku, qty in actual_map.items():
            if sku in existing_skus or qty <= 0:
                continue
            cat = catalog_by_sku.get(sku, {})
            reservation.items.append(MaterialReservationItem(
                sku=sku, name=cat.get('name'), image_url=cat.get('image'),
                quantity_reserved=0, quantity_actual=qty,
            ))
        db.session.commit()
    invalidate_catalog_cache()  # physical stock written off
    return True, result


def cancel_reservation(instance, request_id=None):
    client = get_client()
    ref = external_ref_for(instance.id)
    result = client.cancel_reservation(ref, request_id=request_id)
    if not result.ok:
        return False, result

    reservation = get_reservation(instance.id)
    if reservation is not None:
        reservation.status = MaterialReservationStatus.CANCELLED
        reservation.last_response = result.data
        db.session.commit()
    invalidate_catalog_cache()  # holds released
    return True, result


def edit_reservation(instance, items, catalog_by_sku):
    """Atomically replace an active reservation with new quantities.

    Uses MM Medic's replace=True so the old holds are only released if the new set
    fits — a shortfall leaves the existing reservation untouched (no data loss).
    Returns (ok, result, reservation).
    """
    return create_reservation(instance, items, catalog_by_sku, replace=True)


def adjust_actuals(instance, actuals, catalog_by_sku=None, request_id=None):
    """Correct a consumed reservation (post-event). actuals: [{sku, actual_qty}].

    SKUs not already on the reservation with actual > 0 are recorded as new local
    lines (matching MM Medic's fresh-consumption adjust path).
    """
    catalog_by_sku = catalog_by_sku or {}
    client = get_client()
    ref = external_ref_for(instance.id)
    result = client.adjust_reservation(ref, actuals, request_id=request_id)
    if not result.ok:
        return False, result

    reservation = get_reservation(instance.id)
    if reservation is not None:
        reservation.last_response = result.data
        actual_map = {a['sku']: a['actual_qty'] for a in actuals}
        existing_skus = {it.sku for it in reservation.items}
        for item in reservation.items:
            if item.sku in actual_map:
                item.quantity_actual = actual_map[item.sku]
        for sku, qty in actual_map.items():
            if sku in existing_skus or qty <= 0:
                continue
            cat = catalog_by_sku.get(sku, {})
            reservation.items.append(MaterialReservationItem(
                sku=sku, name=cat.get('name'), image_url=cat.get('image'),
                quantity_reserved=0, quantity_actual=qty,
            ))
        db.session.commit()
    invalidate_catalog_cache()  # stock adjusted
    return True, result


#: Статуси, які звірка має право переглядати.
#:
#: Не лише RESERVED. Штовх статусу -- best effort: він летить окремим потоком
#: без ретраїв, тож будь-який один перехід можна проґавити. Доки звірка
#: дивилась лише на RESERVED, документ, що застряг у SUBMITTED або ISSUED,
#: не лікувався НІКОЛИ -- саме той сценарій, заради якого звірка й існує.
_RECONCILABLE = (
    MaterialReservationStatus.SUBMITTED,
    MaterialReservationStatus.RESERVED,
    MaterialReservationStatus.ISSUED,
)

#: Статус на боці MM Medic -> локальний. Дзеркалить `_STATUS_MAP` приймача
#: вебхука: два різні словники на одну відповідність розійшлися б на першому ж
#: новому значенні.
_REMOTE_TO_LOCAL = {
    'submitted': MaterialReservationStatus.SUBMITTED,
    'approved': MaterialReservationStatus.RESERVED,
    'active': MaterialReservationStatus.RESERVED,
    'issued': MaterialReservationStatus.ISSUED,
    'consumed': MaterialReservationStatus.CONSUMED,
    'completed': MaterialReservationStatus.CONSUMED,
    'rejected': MaterialReservationStatus.REJECTED,
    'cancelled': MaterialReservationStatus.CANCELLED,
    'released': MaterialReservationStatus.CANCELLED,
    'expired': MaterialReservationStatus.EXPIRED,
}


def reconcile_reservation(reservation):
    """Sync one local record with MM Medic (detect consumed / lapsed).

    MM Medic keeps the header 'active' even after its per-line holds expire, so an
    'active' header with no current lines means the reservation lapsed (event
    passed without actuals). Returns True if the local status changed.
    """
    if reservation is None or reservation.status not in _RECONCILABLE:
        return False
    try:
        client = get_client()
    except MMConfigError:
        return False
    result = client.get_reservation(reservation.external_ref)
    if not result.ok:
        return False
    remote = (result.data or {}).get('reservation') or {}
    remote_status = remote.get('status')
    new_status = _REMOTE_TO_LOCAL.get(remote_status)
    if (remote_status in ('active', 'approved')
            and not (remote.get('items') or [])):
        # Порожній «живий» заголовок означає, що утримання протухли.
        new_status = MaterialReservationStatus.EXPIRED
    if not new_status or new_status == reservation.status:
        return False
    reservation.status = new_status
    reservation.last_response = result.data
    db.session.commit()
    logger.info('Reconciled material reservation %s -> %s',
                reservation.external_ref, new_status)
    return True


def send_pending_actuals_reminders(within_days=14, max_items=200):
    """Email admins a reminder to submit actuals for reservations whose event has
    ended but is still RESERVED. Idempotent via actuals_reminder_sent_at.

    Intended for a scheduled job. Returns the number of reminders sent.
    """
    try:
        get_client()  # only remind while the integration is usable
    except MMConfigError:
        return 0
    from app.services.email_service import EmailService

    now = datetime.now(timezone.utc)
    floor = now - timedelta(days=within_days)
    q = (MaterialReservation.query
         .join(CourseInstance, CourseInstance.id == MaterialReservation.instance_id)
         .filter(MaterialReservation.status == MaterialReservationStatus.RESERVED,
                 MaterialReservation.actuals_reminder_sent_at.is_(None),
                 CourseInstance.end_date.isnot(None),
                 CourseInstance.end_date < now,
                 CourseInstance.end_date >= floor)
         .limit(max_items))
    sent = 0
    for reservation in q.all():
        try:
            results = EmailService.send_materials_actuals_reminder(
                reservation, reservation.instance
            )
            # Only mark as reminded if there were recipients to attempt; otherwise
            # leave the flag NULL so it retries once admins/managers are configured.
            if results:
                reservation.actuals_reminder_sent_at = now
                db.session.commit()
                sent += 1
            else:
                db.session.rollback()
        except Exception:
            db.session.rollback()
            logger.exception('actuals reminder failed for %s', reservation.external_ref)
    return sent


def reconcile_stale(max_items=200):
    """Batch reconcile open reservations for instances whose end date passed.

    Intended for a scheduled job. Returns the number of records updated.

    Бере всі незакриті статуси (`_RECONCILABLE`), а не лише RESERVED: штовх
    статусу не має ретраїв, тож документ може застрягти на будь-якому кроці, і
    саме звірка -- єдине, що це виправляє.
    """
    try:
        get_client()
    except MMConfigError:
        return 0
    now = datetime.now(timezone.utc)
    q = (MaterialReservation.query
         .join(CourseInstance, CourseInstance.id == MaterialReservation.instance_id)
         .filter(MaterialReservation.status.in_(_RECONCILABLE),
                 CourseInstance.end_date.isnot(None),
                 CourseInstance.end_date < now)
         .limit(max_items))
    updated = 0
    for reservation in q.all():
        try:
            if reconcile_reservation(reservation):
                updated += 1
        except Exception:
            logger.exception('reconcile failed for %s', reservation.external_ref)
    return updated
