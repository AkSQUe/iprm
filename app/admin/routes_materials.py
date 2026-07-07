"""Admin: резервування витратних матеріалів MM Medic під захід (CourseInstance).

Каталог тягнеться live з MM Medic через підписаний клієнт. Резерв створюється на
MM Medic; після заходу адмін вводить фактичні кількості -> списання/повернення на
MM Medic; локально лишається історія (MaterialReservation).
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from flask import (
    current_app, flash, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.material_reservation import MaterialReservationStatus
from app.services import material_reservation_service as mrs
from app.services import xlsx_io
from app.services.mm_medic_client import MMConfigError

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


def _prefill_dir() -> Path:
    target = Path(current_app.instance_path) / 'material_prefill'
    target.mkdir(parents=True, exist_ok=True)
    return target


def _save_prefill(prefill: dict) -> str:
    """Persist an imported {sku: qty} prefill server-side (cookie sessions cannot
    hold a large catalog). Returns a token for the redirect."""
    token = uuid.uuid4().hex
    (_prefill_dir() / f'{token}.json').write_text(
        json.dumps(prefill), encoding='utf-8',
    )
    return token


def _load_prefill(token: str) -> dict | None:
    """Load + consume a saved prefill. None on missing/invalid token."""
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


def _get_instance(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
    return instance


def _load_catalog():
    """Returns (items, error_message). error_message is None on success."""
    try:
        client = mrs.get_client()
    except MMConfigError as exc:
        return [], str(exc)
    result = client.fetch_catalog()
    if not result.ok:
        return [], result.error or 'Не вдалося отримати каталог MM Medic'
    items = (result.data or {}).get('items') or []
    return items, None


def _build_rows(catalog, reservation, prefill):
    reserved, actual = {}, {}
    if reservation:
        for it in reservation.items:
            reserved[it.sku] = it.quantity_reserved
            actual[it.sku] = it.quantity_actual

    rows, seen = [], set()
    for c in catalog:
        sku = c.get('sku')
        seen.add(sku)
        if prefill and sku in prefill:
            value = prefill[sku]
        elif sku in reserved:
            value = reserved[sku]
        else:
            value = None
        rows.append({
            'sku': sku,
            'name': c.get('name'),
            'image': c.get('image'),
            'available': c.get('available'),
            'is_consumable': c.get('is_consumable'),
            'reserved': reserved.get(sku),
            'actual': actual.get(sku),
            'input': value,
        })

    # Reserved lines that dropped out of the current catalog (now out of stock)
    # still shown so history/actuals stay complete.
    if reservation:
        for it in reservation.items:
            if it.sku not in seen:
                rows.append({
                    'sku': it.sku, 'name': it.name, 'image': it.image_url,
                    'available': None, 'is_consumable': None,
                    'reserved': it.quantity_reserved, 'actual': it.quantity_actual,
                    'input': it.quantity_reserved,
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
    """[{sku, actual_qty}] from every row. Blank -> omit (reserved rows default
    to full consume on MM Medic); explicit 0 -> release; a value on a not-yet-
    reserved row -> on-the-fly addition; negatives ignored."""
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


@admin_bp.route('/instances/<int:instance_id>/materials')
@admin_required
def instance_materials(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    catalog, catalog_error = _load_catalog()
    prefill = _load_prefill(request.args.get('prefill', ''))
    rows = _build_rows(catalog, reservation, prefill)

    is_reserved = bool(reservation) and reservation.status == MaterialReservationStatus.RESERVED
    return render_template(
        'admin/materials.html',
        instance=instance,
        reservation=reservation,
        rows=rows,
        catalog_error=catalog_error,
        is_reserved=is_reserved,
        statuses=MaterialReservationStatus,
    )


@admin_bp.route('/instances/<int:instance_id>/materials/reserve', methods=['POST'])
@admin_required
def instance_materials_reserve(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if reservation and reservation.status == MaterialReservationStatus.RESERVED:
        flash('Резервування вже активне. Щоб змінити — спершу скасуйте його.', 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))

    catalog, catalog_error = _load_catalog()
    if catalog_error:
        flash(catalog_error, 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))

    catalog_by_sku = {c['sku']: c for c in catalog}
    items = [it for it in _items_from_form('quantity') if it['sku'] in catalog_by_sku]
    if not items:
        flash('Не вказано жодної кількості для резервування', 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))

    try:
        ok, result, _res = mrs.create_reservation(instance, items, catalog_by_sku)
    except MMConfigError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))

    if ok:
        audit_logger.info(
            'Admin %s reserved %d materials for instance %s',
            current_user.email, len(items), instance_id,
        )
        flash(f'Зарезервовано {len(items)} позицій на MM Medic', 'success')
    else:
        _flash_result_error(result)
    return redirect(url_for('admin.instance_materials', instance_id=instance_id))


@admin_bp.route('/instances/<int:instance_id>/materials/actuals', methods=['POST'])
@admin_required
def instance_materials_actuals(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if not reservation or reservation.status != MaterialReservationStatus.RESERVED:
        flash('Немає активного резервування для списання', 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))

    actuals = _actuals_from_form()
    # Catalog is loaded best-effort to snapshot names/images for on-the-fly
    # additions; failure here must not block the write-off itself.
    catalog, _err = _load_catalog()
    catalog_by_sku = {c['sku']: c for c in catalog}
    request_id = f'actuals-{instance_id}-{reservation.id}'
    try:
        ok, result = mrs.submit_actuals(
            instance, actuals, catalog_by_sku=catalog_by_sku, request_id=request_id,
        )
    except MMConfigError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))

    if ok:
        audit_logger.info(
            'Admin %s submitted material actuals for instance %s',
            current_user.email, instance_id,
        )
        flash('Фактичні кількості проведено: залишки списано на MM Medic', 'success')
    else:
        _flash_result_error(result)
    return redirect(url_for('admin.instance_materials', instance_id=instance_id))


@admin_bp.route('/instances/<int:instance_id>/materials/cancel', methods=['POST'])
@admin_required
def instance_materials_cancel(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    reservation = mrs.get_reservation(instance_id)
    if not reservation or reservation.status != MaterialReservationStatus.RESERVED:
        flash('Немає активного резервування для скасування', 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))

    request_id = f'cancel-{instance_id}-{reservation.id}'
    try:
        ok, result = mrs.cancel_reservation(instance, request_id=request_id)
    except MMConfigError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))

    if ok:
        audit_logger.info(
            'Admin %s cancelled material reservation for instance %s',
            current_user.email, instance_id,
        )
        flash('Резервування скасовано, залишки повернено на склад MM Medic', 'success')
    else:
        _flash_result_error(result)
    return redirect(url_for('admin.instance_materials', instance_id=instance_id))


@admin_bp.route('/instances/<int:instance_id>/materials/template.xlsx')
@admin_required
def instance_materials_template(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    catalog, catalog_error = _load_catalog()
    if catalog_error:
        flash(catalog_error, 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))

    data = xlsx_io.export_materials_template_xlsx(catalog)
    audit_logger.info(
        'Admin %s downloaded materials template for instance %s',
        current_user.email, instance_id,
    )
    return send_file(
        data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'materials-{instance_id}-{datetime.now().strftime("%Y%m%d-%H%M")}.xlsx',
        max_age=0,
    )


@admin_bp.route('/instances/<int:instance_id>/materials/import-xlsx', methods=['POST'])
@admin_required
def instance_materials_import(instance_id):
    instance = _get_instance(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    f = request.files.get('xlsx')
    if not f or not f.filename:
        flash('Оберіть файл .xlsx для завантаження', 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))
    if not f.filename.lower().endswith('.xlsx'):
        flash('Формат файлу має бути .xlsx', 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))

    token = xlsx_io.save_uploaded_xlsx(f)
    path = xlsx_io.get_uploaded_path(token)
    try:
        prefill = xlsx_io.parse_materials_xlsx(path)
    except Exception as exc:
        logger.exception('materials xlsx parse failed')
        flash(f'Не вдалося прочитати файл: {exc}', 'error')
        return redirect(url_for('admin.instance_materials', instance_id=instance_id))
    finally:
        xlsx_io.cleanup_upload(token)

    token = _save_prefill(prefill)
    flash(
        f'Завантажено {len(prefill)} позицій із файлу — перевірте кількості й збережіть.',
        'success',
    )
    return redirect(url_for('admin.instance_materials', instance_id=instance_id, prefill=token))
