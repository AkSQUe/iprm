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

from app.admin import admin_bp
from app.admin.decorators import admin_required
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
    """Build display rows. `mode` in {reserve, edit, actuals} chooses the input value:
    reserve/edit -> quantity to reserve; actuals -> quantity actually used.
    """
    reserved, actual = {}, {}
    if reservation:
        for it in reservation.items:
            reserved[it.sku] = it.quantity_reserved
            actual[it.sku] = it.quantity_actual

    def _value(sku):
        if prefill and sku in prefill:
            return prefill[sku]
        if mode == 'actuals':
            return actual.get(sku)
        if mode == 'edit':
            return reserved.get(sku)
        return None  # reserve mode starts empty

    rows, seen = [], set()
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
            'value': _value(sku),
        })

    if reservation:
        for it in reservation.items:
            if it.sku not in seen:
                rows.append({
                    'sku': it.sku, 'name': it.name, 'image': it.image_url,
                    'available': None, 'is_consumable': None, 'price': None,
                    'category': None,
                    'reserved': it.quantity_reserved, 'actual': it.quantity_actual,
                    'value': (prefill.get(it.sku) if prefill else
                              (it.quantity_actual if mode == 'actuals' else it.quantity_reserved)),
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
    else:
        flash(f'MM Medic відхилив запит: {result.error or "невідома помилка"}', 'error')


def _redirect_page(instance_id, **kw):
    return redirect(url_for('admin.instance_materials', instance_id=instance_id, **kw))


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/materials')
@admin_required
def instance_materials(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    is_reserved = bool(reservation) and reservation.status == MaterialReservationStatus.RESERVED
    is_consumed = bool(reservation) and reservation.status == MaterialReservationStatus.CONSUMED

    edit = bool(request.args.get('edit')) and is_reserved
    adjust = bool(request.args.get('adjust')) and is_consumed
    if edit:
        mode = 'edit'
    elif adjust or is_consumed:
        mode = 'actuals'  # consumed -> show actual column (read/adjust)
    elif is_reserved:
        mode = 'actuals'
    else:
        mode = 'reserve'

    search = (request.args.get('q') or '').strip() or None
    consumable = request.args.get('consumable', '').lower() in ('1', 'true', 'yes')
    catalog, catalog_error, catalog_stale = _load_catalog(consumable=consumable, search=search)

    templates, _tpl_err = ([], None)
    if mode in ('reserve', 'edit'):
        templates, _tpl_err = mrs.get_templates()

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
        templates=templates,
        mode=mode,
        is_reserved=is_reserved,
        is_consumed=is_consumed,
        est_cost=round(est_cost, 2),
        participants=participants,
        trainer_url=trainer_url,
        statuses=MaterialReservationStatus,
    )


# ---------------------------------------------------------------------------
# Reserve / edit / actuals / adjust / cancel
# ---------------------------------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/materials/reserve', methods=['POST'])
@admin_required
def instance_materials_reserve(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if reservation and reservation.status == MaterialReservationStatus.RESERVED:
        flash('Резервування вже активне. Скористайтесь «Редагувати».', 'error')
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
        flash(f'Подано на погодження {len(items)} позицій на MM Medic', 'success')
    else:
        _flash_result_error(result)
    return _redirect_page(instance_id)


@admin_bp.route('/instances/<int:instance_id>/materials/edit', methods=['POST'])
@admin_required
def instance_materials_edit(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if not reservation or reservation.status != MaterialReservationStatus.RESERVED:
        flash('Немає активного резервування для редагування', 'error')
        return _redirect_page(instance_id)

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
@admin_required
def instance_materials_actuals(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if not reservation or reservation.status != MaterialReservationStatus.RESERVED:
        flash('Немає активного резервування для списання', 'error')
        return _redirect_page(instance_id)

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
@admin_required
def instance_materials_adjust(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if not reservation or reservation.status != MaterialReservationStatus.CONSUMED:
        flash('Коригувати можна лише вже списане резервування', 'error')
        return _redirect_page(instance_id)

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
@admin_required
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
# Templates (bill-of-materials) apply
# ---------------------------------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/materials/apply-template', methods=['POST'])
@admin_required
def instance_materials_apply_template(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    name = (request.form.get('template') or '').strip()
    try:
        multiplier = max(1, int(request.form.get('multiplier') or 1))
    except ValueError:
        multiplier = 1

    templates, err = mrs.get_templates()
    if err:
        flash(err, 'error')
        return _redirect_page(instance_id)
    tpl = next((t for t in templates if t['name'] == name), None)
    if not tpl:
        flash('Шаблон не знайдено', 'error')
        return _redirect_page(instance_id)

    prefill = {}
    for it in tpl.get('items', []):
        sku = it.get('sku')
        qty = it.get('quantity') or 0
        if sku and qty > 0:
            prefill[sku] = qty * multiplier

    if not prefill:
        flash('Шаблон порожній', 'error')
        return _redirect_page(instance_id)

    token = _save_prefill(prefill)
    flash(f'Застосовано шаблон «{name}» ({len(prefill)} позицій). Перевірте й збережіть.',
          'success')
    reservation = mrs.get_reservation(instance_id)
    edit = 1 if (reservation and reservation.status == MaterialReservationStatus.RESERVED) else None
    return _redirect_page(instance_id, prefill=token, edit=edit)


# ---------------------------------------------------------------------------
# XLSX template download + import
# ---------------------------------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/materials/template.xlsx')
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
def materials_overview():
    from app.models.material_reservation import MaterialReservationItem
    f = _overview_filters()
    page = request.args.get('page', 1, type=int)
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

    return render_template('admin/materials_overview.html',
                           reservations=pagination.items, pagination=pagination,
                           counts=counts, filter_status=f['status'],
                           date_from=f['date_from_raw'], date_to=f['date_to_raw'],
                           total_reservations=pagination.total,
                           reserved_units=int(reserved_units or 0),
                           actual_units=int(actual_units or 0),
                           export_cap=_OVERVIEW_EXPORT_CAP,
                           export_capped=pagination.total > _OVERVIEW_EXPORT_CAP,
                           statuses=MaterialReservationStatus)


_OVERVIEW_EXPORT_CAP = 2000


@admin_bp.route('/materials/export.xlsx')
@admin_required
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
@admin_required
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
