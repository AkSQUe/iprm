"""Admin: резервування витратних матеріалів MM Medic під захід (CourseInstance).

Каталог тягнеться live з MM Medic (з коротким кешем) через підписаний клієнт.
Резерв створюється на MM Medic; після заходу адмін вводить фактичні кількості ->
списання/повернення на MM Medic; локально лишається історія (MaterialReservation).
"""
import json
import logging
import uuid
from pathlib import Path

from flask import (
    current_app, flash, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.rbac import permission_required
from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationStatus,
)
from app.services import material_reservation_service as mrs
from app.services import xlsx_io
from app.services.mm_medic_client import MMConfigError

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


# ---------------------------------------------------------------------------
# Prefill (imported/template quantities) -- stored server-side, not in cookie.
# ---------------------------------------------------------------------------

def _prefill_dir() -> Path:
    target = Path(current_app.instance_path) / 'material_prefill'
    target.mkdir(parents=True, exist_ok=True)
    return target


def _save_prefill(prefill: dict) -> str:
    token = uuid.uuid4().hex
    (_prefill_dir() / f'{token}.json').write_text(json.dumps(prefill), encoding='utf-8')
    return token


def _load_prefill(token: str) -> dict | None:
    if not token or not token.isalnum() or len(token) != 32:
        return None
    path = _prefill_dir() / f'{token}.json'
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return None
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_instance(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
    return instance


def _load_catalog(consumable=False, search=None):
    """Returns (items, error, stale)."""
    return mrs.get_catalog(consumable=consumable, search=search)


def _build_rows(catalog, reservation, prefill, mode):
    """Build display rows. `mode` chooses the input value:
    reserve/edit -> quantity to reserve; update -> quantity asked for in the
    still-unapproved request; actuals -> quantity actually used.

    `view` -- читання документа, яким керує MM Medic: тут показуються ЛИШЕ
    рядки самої заявки. Каталог у сотню позицій без жодного поля вводу -- це
    не «більше даних», а шум, крізь який шукають три свої рядки.
    """
    reserved, actual, requested = {}, {}, {}
    if reservation:
        for it in reservation.items:
            reserved[it.sku] = it.quantity_reserved
            actual[it.sku] = it.quantity_actual
            requested[it.sku] = it.quantity_requested

    def _value(sku):
        if prefill and sku in prefill:
            return prefill[sku]
        if mode == 'actuals':
            return actual.get(sku)
        if mode == 'update':
            # Поданої заявки `quantity_reserved` не стосується (утримань ще
            # немає), тому в полі стоїть саме запитане.
            value = requested.get(sku)
            return value if value is not None else reserved.get(sku)
        if mode == 'edit':
            return reserved.get(sku)
        return None  # reserve mode starts empty

    catalog_by_sku = {c.get('sku'): c for c in catalog}
    rows, seen = [], set()
    if mode != 'view':
        for c in catalog:
            sku = c.get('sku')
            seen.add(sku)
            rows.append({
                'sku': sku,
                'name': c.get('name'),
                'image': c.get('image'),
                'available': c.get('available'),
                'is_consumable': c.get('is_consumable'),
                'price': c.get('price'),
                'category': c.get('category'),
                'min_stock': c.get('min_stock') or 0,
                'reserved': reserved.get(sku),
                'actual': actual.get(sku),
                'requested': requested.get(sku),
                'value': _value(sku),
            })

    if reservation:
        for it in reservation.items:
            if it.sku in seen:
                continue
            cat = catalog_by_sku.get(it.sku) or {}
            rows.append({
                'sku': it.sku, 'name': it.name or cat.get('name'),
                'image': it.image_url or cat.get('image'),
                'available': cat.get('available'),
                'is_consumable': cat.get('is_consumable'),
                'price': cat.get('price'),
                'category': cat.get('category'),
                'min_stock': cat.get('min_stock') or 0,
                'reserved': it.quantity_reserved, 'actual': it.quantity_actual,
                'requested': it.quantity_requested,
                'value': (prefill.get(it.sku) if prefill else _value(it.sku)),
            })
    return rows


def _items_from_form(field='quantity'):
    """[{sku, quantity}] from parallel sku[]/<field>[] inputs, qty > 0 only."""
    skus = request.form.getlist('sku')
    qtys = request.form.getlist(field)
    items = []
    for sku, raw in zip(skus, qtys):
        raw = (raw or '').strip()
        if not raw:
            continue
        try:
            n = int(float(raw.replace(',', '.')))
        except ValueError:
            continue
        if n <= 0:
            continue
        items.append({'sku': sku, 'quantity': n})
    return items


def _actuals_from_form():
    """[{sku, actual_qty}] from every row. Blank -> omit; 0 -> release; a value on
    a not-yet-reserved row -> on-the-fly addition; negatives ignored."""
    skus = request.form.getlist('sku')
    acts = request.form.getlist('actual')
    actuals = []
    for sku, raw in zip(skus, acts):
        raw = (raw or '').strip()
        if raw == '':
            continue
        try:
            n = int(float(raw.replace(',', '.')))
        except ValueError:
            continue
        if n < 0:
            continue
        actuals.append({'sku': sku, 'actual_qty': n})
    return actuals


_REASON_LABELS = {
    'unknown_sku': 'немає такого товару',
    'invalid_quantity': 'некоректна кількість',
    'missing_sku': 'порожній артикул',
    'malformed_item': 'некоректний рядок',
    'no_valid_items': 'жодної позиції',
}


#: Статуси, у яких заявка ЖИВА: подавати нову не можна, доки ця не завершилась
#: (погоджена, відмовлена, скасована або списана). Дзеркалить `Status.OPEN` на
#: боці MM Medic -- саме той набір, на якому `submit()` повертає документ як є.
_OPEN_STATUSES = (
    MaterialReservationStatus.SUBMITTED,
    MaterialReservationStatus.RESERVED,
    MaterialReservationStatus.ISSUED,
)

#: Режими, у яких у полі вводиться КІЛЬКІСТЬ до замовлення (а не факт).
_QTY_MODES = ('reserve', 'edit', 'update')

#: Що ІПРМ каже, коли дію виконує MM Medic, а не ми.
_DOCUMENT_OWNED = ('Цією заявкою керує документ MM Medic: видачу, повернення '
                   'і закриття виконує комірник на боці MM Medic.')


#: Відмови MM Medic, у яких сира англійська нічого не пояснює комірнику.
_ERROR_MESSAGES = {
    'actuals_unsupported_for_document': _DOCUMENT_OWNED,
    'adjust_unsupported_for_document': _DOCUMENT_OWNED,
}


def _flash_result_error(result):
    data = result.data if isinstance(result.data, dict) else {}
    status = data.get('status')
    errors = data.get('errors')
    shortfalls = getattr(result, 'shortfalls', None) or []

    if status == 'invalid_items' and errors:
        lines = ', '.join(
            f"{e.get('sku') or '—'} ({_REASON_LABELS.get(e.get('reason'), e.get('reason'))})"
            for e in errors
        )
        flash(f'Некоректні позиції: {lines}', 'error')
    elif shortfalls:
        parts = []
        for s in shortfalls:
            if s.get('reason') == 'unknown_sku':
                parts.append(f"{s.get('sku')} (немає такого товару)")
            else:
                parts.append(
                    f"{s.get('sku')} (потрібно {s.get('requested')}, наявно {s.get('available')})"
                )
        flash(f'Недостатньо матеріалів на складі: {", ".join(parts)}', 'error')
    elif status == 'already_consumed' or result.error == 'already_consumed':
        flash('Резервування вже списано — захід завершено. Змінити неможливо.', 'error')
    elif result.error in _ERROR_MESSAGES:
        flash(_ERROR_MESSAGES[result.error], 'error')
    else:
        flash(f'MM Medic відхилив запит: {result.error or "невідома помилка"}', 'error')


def _redirect_page(instance_id, **kw):
    return redirect(url_for('admin.instance_materials', instance_id=instance_id, **kw))


def _refuse_document(reservation, instance_id, **kw):
    """Відмовити діям утримань для документа. Повертає redirect або None.

    Легасі-списання (`/actuals`, `/adjust`) написане під резерв БЕЗ рядків,
    і для документа воно незворотне: MM Medic закриє заголовок, не створивши
    жодного рядка видачі, тобто собівартість заходу -- те, заради чого
    документ і зʼявився, -- стане недосяжною назавжди. MM Medic відмовляє й сам
    (`actuals_unsupported_for_document`); тут ми не даємо людині натиснути
    кнопку, яка все одно не спрацює, і пояснюємо чому.
    """
    if reservation is not None and reservation.is_mm_document:
        flash(_DOCUMENT_OWNED, 'error')
        return _redirect_page(instance_id, **kw)
    return None


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/materials')
@permission_required('materials.view')
def instance_materials(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    status = reservation.status if reservation else None
    is_submitted = status == MaterialReservationStatus.SUBMITTED
    is_reserved = status == MaterialReservationStatus.RESERVED
    is_consumed = status == MaterialReservationStatus.CONSUMED
    is_mm_document = bool(reservation) and reservation.is_mm_document

    # РЕЖИМ ОБИРАЄТЬСЯ ЗА ТИМ, ЩО З ДОКУМЕНТОМ МОЖНА ЗРОБИТИ, А НЕ ЗА ОДНИМ
    # СТАТУСОМ.
    #
    # Доти гвард питав лише «RESERVED?», і все інше падало в режим подання.
    # Наслідків було два, обидва мовчазні. На SUBMITTED кнопка подання
    # кликала `submit_request` ще раз, MM Medic ідемпотентно повертав той
    # самий документ БЕЗ ЗМІН, дзеркало перебудовувалось із тієї ж відповіді,
    # а людині писало «Подано на погодження N позицій» -- не змінилось нічого,
    # а сказано, що змінилось. На ISSUED -- нормальному стані на весь час
    # заходу -- та сама кнопка ВІДКОЧУВАЛА дзеркало в SUBMITTED і стирала
    # `consumed_at` та `actuals_reminder_sent_at`; звірка це не лікує, бо
    # дивиться лише на заходи, чия дата вже минула.
    #
    # Тепер: поданий документ ведеться правкою (`update_request_items`),
    # усе, чим керує MM Medic, показується лише для читання, а подання
    # доступне рівно тоді, коли відкритої заявки немає.
    edit = bool(request.args.get('edit')) and is_reserved and not is_mm_document
    adjust = bool(request.args.get('adjust')) and is_consumed and not is_mm_document
    if is_submitted:
        mode = 'update'      # заявка на погодженні -> правка переліку
    elif edit:
        mode = 'edit'
    elif is_mm_document:
        mode = 'view'        # видачею і закриттям керує комірник MM Medic
    elif adjust or is_consumed:
        mode = 'actuals'     # consumed -> show actual column (read/adjust)
    elif is_reserved:
        mode = 'actuals'
    elif status in _OPEN_STATUSES:
        mode = 'view'        # відкрита заявка, але не наша -- лише читання
    else:
        mode = 'reserve'

    search = (request.args.get('q') or '').strip() or None
    consumable = request.args.get('consumable', '').lower() in ('1', 'true', 'yes')
    catalog, catalog_error, catalog_stale = _load_catalog(consumable=consumable, search=search)

    kits = mrs.kits_for_instance(instance) if mode in _QTY_MODES else []

    prefill = _load_prefill(request.args.get('prefill', ''))
    rows = _build_rows(catalog, reservation, prefill, mode)

    # Estimated cost of the current selection (reserved or actual, by mode).
    est_cost = 0.0
    price_by_sku = {c.get('sku'): c.get('price') for c in catalog}
    for row in rows:
        price = row.get('price') if row.get('price') is not None else price_by_sku.get(row['sku'])
        qty = row.get('value')
        if price and qty:
            try:
                est_cost += float(price) * int(qty)
            except (TypeError, ValueError):
                pass

    participants = instance.registration_count if hasattr(instance, 'registration_count') else None

    trainer_url = None
    if reservation is not None:
        trainer_url = url_for('main.trainer_materials',
                              token=mrs.make_trainer_token(instance_id), _external=True)

    return render_template(
        'admin/materials.html',
        instance=instance,
        reservation=reservation,
        rows=rows,
        catalog_error=catalog_error,
        catalog_stale=catalog_stale,
        kits=kits,
        mode=mode,
        is_reserved=is_reserved,
        is_consumed=is_consumed,
        is_submitted=is_submitted,
        is_mm_document=is_mm_document,
        est_cost=round(est_cost, 2),
        participants=participants,
        trainer_url=trainer_url,
        statuses=MaterialReservationStatus,
    )


# ---------------------------------------------------------------------------
# Reserve / edit / actuals / adjust / cancel
# ---------------------------------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/materials/reserve', methods=['POST'])
@permission_required('materials.manage')
def instance_materials_reserve(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    # Гейт за «відкрита заявка вже існує», а не за одним статусом. Подання на
    # живий документ MM Medic ідемпотентне: воно поверне його БЕЗ ЗМІН, і
    # єдиним наслідком буде повідомлення про успіх, якого не було. Для
    # ISSUED наслідок гірший -- дзеркало відкочувалось у SUBMITTED.
    if reservation and reservation.status in _OPEN_STATUSES:
        if reservation.status == MaterialReservationStatus.SUBMITTED:
            flash('Заявку вже подано. Змініть перелік і збережіть її.', 'error')
        elif reservation.status == MaterialReservationStatus.RESERVED:
            flash('Резервування вже активне. Скористайтесь «Редагувати».', 'error')
        else:
            flash('Матеріали вже відвантажено на MM Medic — заявку не змінити.',
                  'error')
        return _redirect_page(instance_id)

    catalog, catalog_error, _stale = _load_catalog()
    if catalog_error:
        flash(catalog_error, 'error')
        return _redirect_page(instance_id)

    catalog_by_sku = {c['sku']: c for c in catalog}
    items = [it for it in _items_from_form('quantity') if it['sku'] in catalog_by_sku]
    if not items:
        flash('Не вказано жодної кількості для резервування', 'error')
        return _redirect_page(instance_id)

    try:
        ok, result, _res = mrs.submit_request(instance, items)
    except MMConfigError as exc:
        flash(str(exc), 'error')
        return _redirect_page(instance_id)

    if ok:
        audit_logger.info('Admin %s submitted %d materials for instance %s',
                          current_user.email, len(items), instance_id)
        # MM Medic відповідає `exists`, коли документ уже живий: наш перелік
        # він при цьому НЕ застосовує. Сказати тут «подано» означало б
        # відзвітувати про зміну, якої не сталося.
        if ((result.data or {}).get('status') if isinstance(result.data, dict)
                else None) == 'exists':
            flash('Заявка на MM Medic уже існує — перелік не змінено. '
                  'Відкрийте її та збережіть зміни.', 'error')
        else:
            flash(f'Подано на погодження {len(items)} позицій на MM Medic',
                  'success')
    else:
        _flash_result_error(result)
    return _redirect_page(instance_id)


@admin_bp.route('/instances/<int:instance_id>/materials/update', methods=['POST'])
@permission_required('materials.manage')
def instance_materials_update(instance_id):
    """Переписати перелік ЩЕ НЕ погодженої заявки.

    Той самий екран, що й подання, але інша дія: `submit` ідемпотентний і
    поданий документ не змінює, тому поданий перелік правиться саме тут
    (`/reservations/<ref>/items` на боці MM Medic). Доки маршрут не був
    підключений, виправити подану заявку не міг ніхто -- кнопка подання
    рапортувала успіх, не змінивши нічого.
    """
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if not reservation or reservation.status != MaterialReservationStatus.SUBMITTED:
        flash('Змінити перелік можна лише в заявці на погодженні', 'error')
        return _redirect_page(instance_id)

    catalog, catalog_error, _stale = _load_catalog()
    if catalog_error:
        flash(catalog_error, 'error')
        return _redirect_page(instance_id)

    catalog_by_sku = {c['sku']: c for c in catalog}
    items = [it for it in _items_from_form('quantity') if it['sku'] in catalog_by_sku]
    if not items:
        flash('Не вказано жодної кількості', 'error')
        return _redirect_page(instance_id)

    try:
        ok, result, _res = mrs.update_request_items(instance, items)
    except MMConfigError as exc:
        flash(str(exc), 'error')
        return _redirect_page(instance_id)

    if ok:
        audit_logger.info('Admin %s updated material request for instance %s',
                          current_user.email, instance_id)
        flash(f'Заявку оновлено: {len(items)} позицій', 'success')
    else:
        _flash_result_error(result)
    return _redirect_page(instance_id)


@admin_bp.route('/instances/<int:instance_id>/materials/edit', methods=['POST'])
@permission_required('materials.manage')
def instance_materials_edit(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if not reservation or reservation.status != MaterialReservationStatus.RESERVED:
        flash('Немає активного резервування для редагування', 'error')
        return _redirect_page(instance_id)
    # Легасі-редагування замінює УТРИМАННЯ (replace=True) і не знає про рядки
    # документа: після нього утримання й погоджені кількості показували б
    # різне, а собівартість рахувалась би по рядках, яких у складі вже немає.
    refused = _refuse_document(reservation, instance_id)
    if refused:
        return refused

    catalog, catalog_error, _stale = _load_catalog()
    if catalog_error:
        flash(catalog_error, 'error')
        return _redirect_page(instance_id, edit=1)

    catalog_by_sku = {c['sku']: c for c in catalog}
    items = [it for it in _items_from_form('quantity') if it['sku'] in catalog_by_sku]
    if not items:
        flash('Не вказано жодної кількості', 'error')
        return _redirect_page(instance_id, edit=1)

    try:
        ok, result, _res = mrs.edit_reservation(instance, items, catalog_by_sku)
    except MMConfigError as exc:
        flash(str(exc), 'error')
        return _redirect_page(instance_id, edit=1)

    if ok:
        audit_logger.info('Admin %s edited material reservation for instance %s',
                          current_user.email, instance_id)
        flash('Резервування оновлено', 'success')
        return _redirect_page(instance_id)
    _flash_result_error(result)
    return _redirect_page(instance_id, edit=1)


@admin_bp.route('/instances/<int:instance_id>/materials/actuals', methods=['POST'])
@permission_required('materials.manage')
def instance_materials_actuals(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if not reservation or reservation.status != MaterialReservationStatus.RESERVED:
        flash('Немає активного резервування для списання', 'error')
        return _redirect_page(instance_id)
    refused = _refuse_document(reservation, instance_id)
    if refused:
        return refused

    actuals = _actuals_from_form()
    catalog, _err, _stale = _load_catalog()
    catalog_by_sku = {c['sku']: c for c in catalog}
    request_id = f'actuals-{instance_id}-{reservation.id}'
    try:
        ok, result = mrs.submit_actuals(instance, actuals, catalog_by_sku=catalog_by_sku,
                                        request_id=request_id)
    except MMConfigError as exc:
        flash(str(exc), 'error')
        return _redirect_page(instance_id)

    if ok:
        audit_logger.info('Admin %s submitted material actuals for instance %s',
                          current_user.email, instance_id)
        flash('Фактичні кількості проведено: залишки списано на MM Medic', 'success')
    else:
        _flash_result_error(result)
    return _redirect_page(instance_id)


@admin_bp.route('/instances/<int:instance_id>/materials/adjust', methods=['POST'])
@permission_required('materials.manage')
def instance_materials_adjust(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if not reservation or reservation.status != MaterialReservationStatus.CONSUMED:
        flash('Коригувати можна лише вже списане резервування', 'error')
        return _redirect_page(instance_id)
    refused = _refuse_document(reservation, instance_id)
    if refused:
        return refused

    actuals = _actuals_from_form()
    catalog, _err, _stale = _load_catalog()
    catalog_by_sku = {c['sku']: c for c in catalog}
    request_id = f'adjust-{instance_id}-{reservation.id}-{uuid.uuid4().hex[:8]}'
    try:
        ok, result = mrs.adjust_actuals(instance, actuals, catalog_by_sku=catalog_by_sku,
                                        request_id=request_id)
    except MMConfigError as exc:
        flash(str(exc), 'error')
        return _redirect_page(instance_id)

    if ok:
        audit_logger.info('Admin %s adjusted material actuals for instance %s',
                          current_user.email, instance_id)
        flash('Коригування проведено на MM Medic', 'success')
    else:
        _flash_result_error(result)
    return _redirect_page(instance_id)


@admin_bp.route('/instances/<int:instance_id>/materials/cancel', methods=['POST'])
@permission_required('materials.manage')
def instance_materials_cancel(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if not reservation or reservation.status != MaterialReservationStatus.RESERVED:
        flash('Немає активного резервування для скасування', 'error')
        return _redirect_page(instance_id)

    request_id = f'cancel-{instance_id}-{reservation.id}'
    try:
        ok, result = mrs.cancel_reservation(instance, request_id=request_id)
    except MMConfigError as exc:
        flash(str(exc), 'error')
        return _redirect_page(instance_id)

    if ok:
        audit_logger.info('Admin %s cancelled material reservation for instance %s',
                          current_user.email, instance_id)
        flash('Резервування скасовано, залишки повернено на склад MM Medic', 'success')
    else:
        _flash_result_error(result)
    return _redirect_page(instance_id)


# ---------------------------------------------------------------------------
# Kits (Task 5: replaces the remote MM Medic template) apply
# ---------------------------------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/materials/apply-template', methods=['POST'])
@permission_required('materials.manage')
def instance_materials_apply_template(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    # Selected by id, not name: a kit's name can be renamed from the admin
    # screen (Task 4), and an id survives that rename while a name match
    # would silently stop finding the kit.
    try:
        kit_id = int(request.form.get('kit_id') or 0)
    except ValueError:
        kit_id = 0
    try:
        multiplier = max(1, int(request.form.get('multiplier') or 1))
    except ValueError:
        multiplier = 1

    # Only a kit this instance could actually be offered (its course's own,
    # or universal, and active) is eligible -- same set the picker renders.
    kit = next((k for k in mrs.kits_for_instance(instance) if k.id == kit_id), None)
    if not kit:
        flash('Комплект не знайдено', 'error')
        return _redirect_page(instance_id)

    prefill = {}
    for it in kit.items:
        if it.sku and it.quantity > 0:
            prefill[it.sku] = it.quantity * multiplier

    if not prefill:
        flash('Комплект порожній', 'error')
        return _redirect_page(instance_id)

    token = _save_prefill(prefill)
    flash(f'Застосовано комплект «{kit.name}» ({len(prefill)} позицій). Перевірте й збережіть.',
          'success')
    reservation = mrs.get_reservation(instance_id)
    edit = 1 if (reservation and reservation.status == MaterialReservationStatus.RESERVED) else None
    return _redirect_page(instance_id, prefill=token, edit=edit)


# ---------------------------------------------------------------------------
# XLSX template download + import
# ---------------------------------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/materials/template.xlsx')
@permission_required('materials.view')
def instance_materials_template(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    catalog, catalog_error, _stale = _load_catalog()
    if catalog_error and not catalog:
        flash(catalog_error, 'error')
        return _redirect_page(instance_id)

    data = xlsx_io.export_materials_template_xlsx(catalog)
    audit_logger.info('Admin %s downloaded materials template for instance %s',
                      current_user.email, instance_id)
    return send_file(
        data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=_materials_filename(instance),
        max_age=0,
    )


def _materials_filename(instance):
    """'Витр. мат-и на {Дата} {Курс}.xlsx' -- з очищенням символів, недопустимих
    у назві файлу."""
    import re
    date = instance.start_date.strftime('%d.%m.%Y') if instance.start_date else ''
    course = instance.course.title if instance.course else 'Захід'
    raw = f'Витр. мат-и на {date} {course}'.strip()
    safe = re.sub(r'[\\/:*?"<>|]', '', raw)          # заборонені у файлових назвах
    safe = re.sub(r'\s+', ' ', safe).strip()
    return f'{safe}.xlsx'


@admin_bp.route('/instances/<int:instance_id>/materials/import-xlsx', methods=['POST'])
@permission_required('materials.import')
def instance_materials_import(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    edit = request.form.get('edit')
    f = request.files.get('xlsx')
    if not f or not f.filename:
        flash('Оберіть файл .xlsx для завантаження', 'error')
        return _redirect_page(instance_id, edit=edit or None)
    if not f.filename.lower().endswith('.xlsx'):
        flash('Формат файлу має бути .xlsx', 'error')
        return _redirect_page(instance_id, edit=edit or None)

    token = xlsx_io.save_uploaded_xlsx(f)
    path = xlsx_io.get_uploaded_path(token)
    try:
        prefill = xlsx_io.parse_materials_xlsx(path)
    except Exception as exc:
        logger.exception('materials xlsx parse failed')
        flash(f'Не вдалося прочитати файл: {exc}', 'error')
        return _redirect_page(instance_id, edit=edit or None)
    finally:
        xlsx_io.cleanup_upload(token)

    ptoken = _save_prefill(prefill)
    flash(f'Завантажено {len(prefill)} позицій із файлу — перевірте кількості й збережіть.',
          'success')
    return _redirect_page(instance_id, prefill=ptoken, edit=edit or None)


# ---------------------------------------------------------------------------
# Picking list (printable) + overview
# ---------------------------------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/materials/picking-list')
@permission_required('materials.view')
def instance_materials_picking(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))
    reservation = mrs.get_reservation(instance_id)
    if not reservation:
        flash('Для цього заходу немає резервування', 'error')
        return _redirect_page(instance_id)
    return render_template('admin/materials_picking.html',
                           instance=instance, reservation=reservation)


_OVERVIEW_PER_PAGE = 50


def _parse_date(value):
    from datetime import datetime as _dt
    value = (value or '').strip()
    if not value:
        return None
    try:
        return _dt.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None


def _overview_filters():
    """Read + normalize overview filters from the query string."""
    return {
        'status': request.args.get('status') or '',
        'date_from': _parse_date(request.args.get('date_from')),
        'date_to': _parse_date(request.args.get('date_to')),
        'date_from_raw': (request.args.get('date_from') or '').strip(),
        'date_to_raw': (request.args.get('date_to') or '').strip(),
    }


def _apply_overview_filters(query, f):
    from datetime import timedelta
    if f['status']:
        query = query.filter(MaterialReservation.status == f['status'])
    if f['date_from']:
        query = query.filter(CourseInstance.start_date >= f['date_from'])
    if f['date_to']:
        query = query.filter(CourseInstance.start_date < f['date_to'] + timedelta(days=1))
    return query


def _overview_query(f):
    query = (MaterialReservation.query
             .join(CourseInstance, CourseInstance.id == MaterialReservation.instance_id))
    return _apply_overview_filters(query, f).order_by(MaterialReservation.created_at.desc())


@admin_bp.route('/materials')
@permission_required('materials.view')
def materials_overview():
    from app.models.material_reservation import MaterialReservationItem
    f = _overview_filters()
    page = _listing.page_arg()
    query = _overview_query(f)
    pagination = query.paginate(page=page, per_page=_OVERVIEW_PER_PAGE, error_out=False)

    counts = dict(
        db.session.query(MaterialReservation.status, db.func.count(MaterialReservation.id))
        .group_by(MaterialReservation.status).all()
    )

    # Unit totals over the FILTERED set (not just the page).
    totals_q = (db.session.query(
                    db.func.coalesce(db.func.sum(MaterialReservationItem.quantity_reserved), 0),
                    db.func.coalesce(db.func.sum(MaterialReservationItem.quantity_actual), 0),
                )
                .select_from(MaterialReservation)
                .join(CourseInstance, CourseInstance.id == MaterialReservation.instance_id)
                .join(MaterialReservationItem,
                      MaterialReservationItem.reservation_id == MaterialReservation.id))
    reserved_units, actual_units = _apply_overview_filters(totals_q, f).first()

    # Панель фільтрів дизайн-системи читає один dict `values` і будує всі
    # посилання сама (чіпси, «Скинути все», експорт), тому зріз віддаємо ще й
    # у її форматі. Старі три змінні лишаються: на них тримаються картки-зрізи.
    filters = {
        'status': f['status'],
        'date_from': f['date_from_raw'],
        'date_to': f['date_to_raw'],
    }
    return render_template('admin/materials_overview.html',
                           reservations=pagination.items, pagination=pagination,
                           counts=counts, filter_status=f['status'],
                           date_from=f['date_from_raw'], date_to=f['date_to_raw'],
                           filters=filters,
                           filter_args={k: v for k, v in filters.items() if v},
                           status_options=[
                               (key, MaterialReservationStatus.LABELS[key])
                               for key in MaterialReservationStatus.ALL
                           ],
                           total_reservations=pagination.total,
                           reserved_units=int(reserved_units or 0),
                           actual_units=int(actual_units or 0),
                           export_cap=_OVERVIEW_EXPORT_CAP,
                           export_capped=pagination.total > _OVERVIEW_EXPORT_CAP,
                           statuses=MaterialReservationStatus)


_OVERVIEW_EXPORT_CAP = 2000


@admin_bp.route('/materials/export.xlsx')
@permission_required('materials.export')
def materials_overview_export():
    f = _overview_filters()
    reservations = _overview_query(f).limit(_OVERVIEW_EXPORT_CAP).all()
    if len(reservations) >= _OVERVIEW_EXPORT_CAP:
        logger.warning('materials export hit the %d-row cap; result truncated',
                       _OVERVIEW_EXPORT_CAP)
    data = xlsx_io.export_material_reservations_xlsx(reservations)
    audit_logger.info('Admin %s exported material reservations overview', current_user.email)
    return send_file(
        data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='material-reservations.xlsx',
        max_age=0,
    )


@admin_bp.route('/materials/reconcile', methods=['POST'])
@permission_required('materials.manage')
def materials_reconcile_now():
    # Bound the manual trigger: each item is a live MM Medic HTTP call, so cap it
    # to keep the request responsive; the scheduled job handles the full backlog.
    try:
        updated = mrs.reconcile_stale(max_items=50)
        reminded = mrs.send_pending_actuals_reminders(max_items=50)
    except Exception:
        logger.exception('manual materials reconcile failed')
        flash('Не вдалося виконати звірку', 'error')
        return redirect(url_for('admin.materials_overview'))
    flash(f'Звірку виконано: оновлено {updated}, нагадувань надіслано {reminded}.', 'success')
    return redirect(url_for('admin.materials_overview'))
