"""IPRM-side orchestration for MM Medic consumable-material reservations.

Wraps MMMedicClient calls and persists the local MaterialReservation history so
admin routes stay thin. The source of truth for stock is MM Medic; these records
are IPRM's own audit keyed to a CourseInstance.
"""
from datetime import datetime, timezone

from app.extensions import db
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem, MaterialReservationStatus,
)
from app.models.site_settings import SiteSettings
from app.services.mm_medic_client import MMMedicClient


def external_ref_for(instance_id) -> str:
    return f'iprm-instance-{instance_id}'


def get_client() -> MMMedicClient:
    """Raises MMConfigError if integration disabled/misconfigured."""
    return MMMedicClient.from_settings(SiteSettings.get())


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


def create_reservation(instance, items, catalog_by_sku):
    """Reserve `items` [{sku, quantity}] on MM Medic and persist locally.

    Returns (ok, result, reservation).
    """
    client = get_client()
    ref = external_ref_for(instance.id)
    result = client.create_reservation(ref, _event_meta(instance), items)
    if not result.ok:
        return False, result, None

    reservation = get_reservation(instance.id)
    if reservation is None:
        reservation = MaterialReservation(instance_id=instance.id, external_ref=ref)
        db.session.add(reservation)
    reservation.status = MaterialReservationStatus.RESERVED
    reservation.sent_at = datetime.now(timezone.utc)
    reservation.consumed_at = None
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
    return True, result
