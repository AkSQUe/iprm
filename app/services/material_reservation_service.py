"""IPRM-side orchestration for MM Medic consumable-material reservations.

Wraps MMMedicClient calls and persists the local MaterialReservation history so
admin routes stay thin. The source of truth for stock is MM Medic; these records
are IPRM's own audit keyed to a CourseInstance.
"""
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_

from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.material_kit import MaterialKit
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

    # Рівно те, що виробляє `external_ref_for`: десяткове число без провідних
    # нулів. Ні `int()`, ні `isdigit()` для цього не годяться, і обидва тут уже
    # були:
    #
    # * `int()` приймає `'1_0'`, `' 10'`, `'+10'` -- усі вказують на той самий
    #   захід, але зберігаються під ІНШИМ `external_ref` (унікальність стоїть
    #   саме на ньому), даючи два документи на один захід;
    # * `isdigit()` пропускає провідні нулі (`'05'` -> захід 5) і не-ASCII
    #   цифри (`'٥'` -> 5) -- та сама дірка. Гірше: `'²'.isdigit()` істинне, а
    #   `int('²')` кидає ValueError, тож перевірка через `isdigit` без
    #   `try/except` давала неспійманий 500.
    if not re.fullmatch(r'[1-9][0-9]*', raw):
        return None
    value = int(raw)  # після fullmatch не кидає

    # Межа BIGINT: більше значення дає psycopg2 NumericValueOutOfRange уже на
    # SELECT, тобто 500 замість охайного «не знаємо такого».
    if value > 9223372036854775807:
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
    """Fetch material templates (BOM) over the MM Medic partner API. Returns
    (templates, error).

    Task 5 moved the materials page's prefill source to local MaterialKit
    records (see `kits_for_instance` below) -- ІPRM, not MM Medic, knows which
    set of materials belongs to which course. This function is no longer
    called from that page. It stays because the partner endpoint it calls
    (`/api/partner/iprm/templates`) is still live on the MM Medic side, and
    retiring it is a later plan's job, in a specific order: ІPRM stops
    calling first (done here), then MM Medic removes the endpoint. Deleting
    this function now would strand that route with no caller to prove it is
    safe to remove.

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


def kits_for_instance(instance):
    """Active material kits available to this instance: its course's own kits
    plus the universal ones (`course_id IS NULL`), see app/models/material_kit.py.

    Replaces `get_templates()` as the materials page's prefill source (Task 5).
    """
    return (
        MaterialKit.query
        .filter(MaterialKit.is_active.is_(True))
        .filter(or_(MaterialKit.course_id == instance.course_id,
                    MaterialKit.course_id.is_(None)))
        .order_by(MaterialKit.name)
        .all()
    )


def get_reservation(instance_id):
    return MaterialReservation.query.filter_by(instance_id=instance_id).first()


def confirm_reservation(reservation, comment):
    """Trainer confirms the prepared kit via the public `/materials/<token>`
    page (app/main/routes.py:trainer_materials_confirm). Local-only -- MM
    Medic is not involved, this is IPRM's own record of what the trainer
    said, since the trainer never logs in anywhere.

    Idempotent: `trainer_confirmed_at` is set only the first time. A second
    confirmation (e.g. a clarification the trainer adds an hour later) must
    not look like an error, and must not move the original timestamp.
    `trainer_comment` is always overwritten with what was submitted --
    including clearing it to NULL when the field comes back blank, so what
    is in the box is always what gets saved.
    """
    reservation.trainer_comment = (comment or '').strip() or None
    if reservation.trainer_confirmed_at is None:
        reservation.trainer_confirmed_at = datetime.now(timezone.utc)
    db.session.commit()


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


def _submitter_id():
    """Хто подав заявку в ІПРМ -- `created_by_id`. IPRM has no role system, so
    this is the only accountability trail available (plan 5.3). None outside
    a request context or for an anonymous caller -- guarded the same way
    `_actor()` in promo_service.py is, since `current_user` raises when
    evaluated with no request context (e.g. a direct service-layer call in
    tests or a future scheduler-driven resubmit)."""
    try:
        from flask_login import current_user
        if current_user and current_user.is_authenticated:
            return current_user.id
    except Exception:
        pass
    return None


def submit_request(instance, items):
    """File `items` [{sku, quantity}] on MM Medic as a request awaiting approval,
    and persist locally. Unlike `create_reservation`, this does NOT put a hold on
    stock -- the warehouse approves (or rejects) it separately, which is what
    produces the actual hold on MM Medic's side.

    The local row snapshot is built from the partner's RESPONSE
    (`result.data['reservation']['items']`), not from the `items` we sent. The
    response is the authority; our payload is only a request -- MM Medic is
    free to leave it unapplied (a repeat submit on an already-open document
    returns that document as-is, unchanged). Building rows from what we sent
    would silently drift the local snapshot from what MM Medic actually holds
    in exactly that case. `apply_items` is the one place this partner-items-
    to-local-rows mapping lives (the status webhook and
    `reconcile_reservation` already go through it); a second, hand-rolled copy
    here is exactly what its own docstring warns will drift on the first edit.

    Returns (ok, result, reservation).
    """
    client = get_client()
    ref = external_ref_for(instance.id)
    result = client.submit_request(ref, _event_meta(instance), items)
    if not result.ok:
        return False, result, None

    reservation = get_reservation(instance.id)
    if reservation is None:
        reservation = MaterialReservation(instance_id=instance.id, external_ref=ref)
        db.session.add(reservation)
    reservation.status = MaterialReservationStatus.SUBMITTED
    reservation.sent_at = datetime.now(timezone.utc)
    reservation.consumed_at = None
    reservation.actuals_reminder_sent_at = None  # fresh cycle -> reminder eligible again
    reservation.last_response = result.data
    submitter_id = _submitter_id()
    if submitter_id is not None:
        reservation.created_by_id = submitter_id

    remote = (result.data or {}).get('reservation') or {}
    apply_items(
        reservation, remote.get('items') or [],
        MaterialReservationStatus.SUBMITTED, True,
    )

    db.session.commit()
    invalidate_catalog_cache()  # derived availability changed
    # Note: the "request submitted" notification is sent by MM Medic to its
    # storekeeper (warehouse managers); IPRM does not email the trainer.
    return True, result, reservation


def update_request_items(instance, items):
    """Переписати перелік ЩЕ НЕ погодженої заявки на MM Medic.

    Окремо від `submit_request`, і це не дублювання: подання ідемпотентне за
    задумом (повтор на живий документ повертає його БЕЗ ЗМІН), а правка
    навпаки мусить перезаписати перелік. Доки правка не була підключена,
    єдиною доступною дією для поданої заявки лишалось повторне подання -- і
    воно рапортувало успіх, не змінивши нічого з жодного боку.

    Рядки, яких у відповіді немає, ВИДАЛЯЄМО. `apply_items` цього не робить
    свідомо: вона розбирає й часткові штовхи, де відсутність рядка не
    означає його зникнення. Тут випадок інший -- відповідь на правку це
    повний знімок документа, і залишений локальний рядок показував би в
    пікінг-листі позицію, від якої людина щойно відмовилась.

    Returns (ok, result, reservation).
    """
    client = get_client()
    ref = external_ref_for(instance.id)
    result = client.update_request_items(ref, items)
    if not result.ok:
        return False, result, None

    reservation = get_reservation(instance.id)
    if reservation is not None:
        reservation.sent_at = datetime.now(timezone.utc)
        reservation.last_response = result.data
        remote = (result.data or {}).get('reservation') or {}
        remote_items = remote.get('items') or []
        apply_items(reservation, remote_items,
                    MaterialReservationStatus.SUBMITTED, True)
        kept = {raw.get('sku') for raw in remote_items
                if isinstance(raw, dict) and raw.get('sku')}
        for existing in list(reservation.items):
            if existing.sku not in kept:
                reservation.items.remove(existing)
        db.session.commit()
    invalidate_catalog_cache()  # перелік змінився -> перерахована наявність
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

#: Порядок основної лінії життєвого циклу. Звірка має право ПРОСУВАТИ документ,
#: але не відкочувати.
#:
#: Без цього розширення `_RECONCILABLE` дало неочікуваний ефект: для
#: відвантаженого (ISSUED) документа партнер і далі віддає legacy-заголовок
#: `active`, мапа перетворює його на RESERVED, і звірка «повертала» документ у
#: зарезервований стан -- тобто знову робила його редагованим і придатним до
#: повторної видачі. Штовх такого зробити не міг: він приходить на кожен
#: перехід уперед, а звірка бачить лише поточний знімок і не знає, наскільки
#: далеко ми вже пройшли.
_STAGE_ORDER = {
    MaterialReservationStatus.DRAFT: 0,
    MaterialReservationStatus.SUBMITTED: 1,
    MaterialReservationStatus.RESERVED: 2,
    MaterialReservationStatus.ISSUED: 3,
    MaterialReservationStatus.CONSUMED: 4,
}

#: Завершення поза основною лінією: можуть прилетіти на будь-якому кроці.
_TERMINAL_BRANCHES = (
    MaterialReservationStatus.REJECTED,
    MaterialReservationStatus.CANCELLED,
    MaterialReservationStatus.EXPIRED,
)


def _may_advance(current, new_status) -> bool:
    """Чи має звірка право застосувати цей статус."""
    if new_status in _TERMINAL_BRANCHES:
        return True
    return (_STAGE_ORDER.get(new_status, -1)
            > _STAGE_ORDER.get(current, -1))

#: Статус на боці MM Medic -> локальний. ЄДИНЕ джерело цієї відповідності:
#: приймач вебхука (`app/api/mm_status.py`) імпортує саме її. Дві літеральні
#: копії тут уже були, і саме вони розійшлися -- не ключами, а правилом.
#:
#: 'active' (legacy) і 'approved' (новий) обидва дають RESERVED: обидва
#: означають «утримання існує». Одне локальне значення на два віддалених -- те,
#: що дозволяє шести гейтам `status == RESERVED` в admin/routes_materials.py
#: лишатись коректними. 'consumed' і 'completed' так само діляться CONSUMED.
REMOTE_TO_LOCAL = {
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
        cost = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None
    # NaN та Infinity конструюються успішно, і обидва шкодять по-різному.
    # NaN не дорівнює сам собі, тож звірка `getattr(item, attr) != value`
    # завжди істинна: кожен опит рапортує «змінилось», комітить і пише в лог.
    # Infinity PostgreSQL відхиляє на вставці -- 500 на публічному вебхуці.
    # Наш відправник такого не шле; це загартування зовні досяжної точки.
    if not cost.is_finite():
        return None
    return cost


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


def apply_items(reservation, items, local_status, has_items_key):
    """Оновити рядки дзеркала зі знімка партнера. Повертає True, якщо змінилось.

    Живе в сервісі, а не в модулі API, бо шляхів надходження стану ДВА:
    штовх (`mm_status`) і фонова звірка (`reconcile_reservation`). Копія
    цієї логіки в кожному з них розійшлася б на першій же правці, і тоді
    локальний стан залежав би від того, який шлях спрацював першим -- рівно
    та помилка, від якої вже застерігає спільний `REMOTE_TO_LOCAL`.

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


def reconcile_reservation(reservation):
    """Sync one local record with MM Medic (detect consumed / lapsed).

    MM Medic keeps the header 'active' even after its per-line holds expire, so an
    'active' header with no current lines means the reservation lapsed (event
    passed without actuals). Returns True if anything changed -- the header
    status, the line items, or both. A lines-only change (status unchanged) is
    exactly the case this function exists to catch: the header push is a
    daemon thread with no retries, so a lost terminal push must still be
    repaired here even when the status snapshot agrees with what we already
    have.
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
    new_status = REMOTE_TO_LOCAL.get(remote_status)
    if (reservation.status == MaterialReservationStatus.RESERVED
            and remote_status in ('active', 'approved')
            and not (remote.get('items') or [])):
        # Порожній «живий» заголовок означає, що утримання протухли.
        #
        # Евристика справедлива ЛИШЕ для RESERVED. Для ISSUED порожній `items`
        # -- це норма: матеріали видали, утримання зняли, а legacy-заголовок на
        # боці MM Medic лишається `active`. Доки перевірки на локальний статус
        # тут не було, розширення `_RECONCILABLE` перемарковувало коректно
        # відвантажений документ у EXPIRED, і НЕОБОРОТНО: EXPIRED у
        # `_RECONCILABLE` не входить, тож звірка більше ніколи на нього не
        # подивиться, а партнер завершений стан не перештовхує.
        new_status = MaterialReservationStatus.EXPIRED

    if new_status and not _may_advance(reservation.status, new_status):
        # Знімок партнера відстає від того, що ми вже знаємо. Мовчати тут
        # правильно: це не помилка, а нормальний стан legacy-заголовка.
        new_status = None

    status_changed = bool(new_status and new_status != reservation.status)

    # Рядки розбираються під ТИМ статусом, який справді набуде чинності.
    # Порядок тут несучий, а не косметичний: `apply_items` рахує ознаку
    # `terminal` саме з цього аргументу, і під нетермінальним прочитанням
    # термінального знімка спрацьовує гілка «`quantity` це погоджене» --
    # тобто `quantity_reserved` затирається спожитою цифрою. Саме та
    # регресія, яку описує докстрінг `apply_items`.
    effective_status = new_status if status_changed else reservation.status

    remote_items = remote.get('items')
    items_changed = apply_items(
        reservation, remote_items or [], effective_status,
        isinstance(remote_items, list),
    )

    if status_changed:
        reservation.status = new_status

    if not (status_changed or items_changed):
        return False

    reservation.last_response = result.data
    db.session.commit()
    if status_changed:
        logger.info('Reconciled material reservation %s -> %s',
                    reservation.external_ref, new_status)
    else:
        logger.info('Reconciled material reservation %s (lines only)',
                    reservation.external_ref)
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

    Intended for a scheduled job. Returns the number of records updated -- a
    record counts even if only its line items (cost, quantities) changed and
    the header status stayed put; "updated" already covers that honestly, no
    narrower "status changed" claim is made here or by the callers that log
    this count.

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
