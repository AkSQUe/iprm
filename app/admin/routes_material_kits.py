"""Admin CRUD комплектів матеріалів (MaterialKit/MaterialKitItem).

Комплект -- стандартний набір позицій під курс, зібраний тут, у ІПРМ:
саме ІПРМ знає, який набір відповідає якому курсу. MM Medic лишається
складом, що виконує заявку (app.services.material_reservation_service),
а не джерелом правди про її вміст -- див. app/models/material_kit.py.

Task 5 застосовує готовий комплект до конкретного заходу; ця сторінка
лише керує самими комплектами і не чіпає MaterialReservation.
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import MaterialKitForm
from app.extensions import db
from app.models.course import Course
from app.models.material_kit import MaterialKit, MaterialKitItem
from app.services import material_reservation_service as mrs

audit_logger = logging.getLogger('audit')

UNIVERSAL_LABEL = '— Універсальний (підходить будь-якому курсу) —'


def _populate_course_choices(form):
    """Курси для прив'язки комплекту + явний варіант "універсальний".

    Порожній варіант навмисно ПЕРШИЙ і з власним підписом: різниця між
    "адмін не обрав курс" і "адмін свідомо зробив комплект універсальним"
    інакше не видима -- порожній вибір без підпису виглядає як помилка
    форми, а не як рішення.
    """
    courses = Course.query.order_by(Course.title).all()
    form.course_id.choices = [('', UNIVERSAL_LABEL)] + [
        (str(c.id), c.title) for c in courses
    ]


def _apply_form(form, kit):
    kit.name = form.name.data.strip()
    kit.course_id = int(form.course_id.data) if form.course_id.data else None
    kit.is_default = form.is_default.data
    kit.is_active = form.is_active.data
    kit.notes = (form.notes.data or '').strip() or None


def _kit_or_404_redirect(kit_id):
    kit = db.session.get(MaterialKit, kit_id)
    if not kit:
        flash('Комплект не знайдено', 'error')
        return None
    return kit


@admin_bp.route('/material-kits')
@admin_required
def material_kits_list():
    kits = MaterialKit.query.order_by(MaterialKit.name).all()
    return render_template('admin/material_kits.html', kits=kits)


@admin_bp.route('/material-kits/new', methods=['GET', 'POST'])
@admin_required
def material_kit_create():
    form = MaterialKitForm()
    _populate_course_choices(form)

    if form.validate_on_submit():
        kit = MaterialKit()
        _apply_form(form, kit)
        db.session.add(kit)
        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s created material kit #%s ("%s") course_id=%s',
                current_user.email, kit.id, kit.name, kit.course_id,
            )
            flash('Комплект створено. Додайте позиції з каталогу MM Medic.', 'success')
            return redirect(url_for('admin.material_kit_edit', kit_id=kit.id))
        except Exception:
            db.session.rollback()
            audit_logger.exception('Failed to create material kit')
            flash('Помилка при збереженні', 'error')

    return render_template(
        'admin/material_kit_edit.html', form=form, kit=None,
        catalog=[], catalog_error=None, catalog_stale=False,
    )


@admin_bp.route('/material-kits/<int:kit_id>', methods=['GET', 'POST'])
@admin_required
def material_kit_edit(kit_id):
    kit = _kit_or_404_redirect(kit_id)
    if kit is None:
        return redirect(url_for('admin.material_kits_list'))

    form = MaterialKitForm(obj=kit)
    _populate_course_choices(form)
    if request.method == 'GET':
        form.course_id.data = str(kit.course_id) if kit.course_id else ''

    if form.validate_on_submit():
        _apply_form(form, kit)
        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s updated material kit #%s ("%s")',
                current_user.email, kit.id, kit.name,
            )
            flash('Комплект оновлено', 'success')
            return redirect(url_for('admin.material_kit_edit', kit_id=kit.id))
        except Exception:
            db.session.rollback()
            audit_logger.exception('Failed to update material kit #%s', kit_id)
            flash('Помилка при збереженні', 'error')

    catalog, catalog_error, catalog_stale = mrs.get_catalog(consumable=True)
    existing_skus = {item.sku for item in kit.items}
    catalog = [c for c in catalog if c.get('sku') not in existing_skus]

    return render_template(
        'admin/material_kit_edit.html', form=form, kit=kit,
        catalog=catalog, catalog_error=catalog_error, catalog_stale=catalog_stale,
    )


@admin_bp.route('/material-kits/<int:kit_id>/delete', methods=['POST'])
@admin_required
def material_kit_delete(kit_id):
    kit = _kit_or_404_redirect(kit_id)
    if kit is None:
        return redirect(url_for('admin.material_kits_list'))
    name = kit.name

    db.session.delete(kit)
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s deleted material kit #%s ("%s")',
            current_user.email, kit_id, name,
        )
        flash(f'Комплект «{name}» видалено', 'success')
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to delete material kit #%s', kit_id)
        flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.material_kits_list'))


@admin_bp.route('/material-kits/<int:kit_id>/items/add', methods=['POST'])
@admin_required
def material_kit_item_add(kit_id):
    kit = _kit_or_404_redirect(kit_id)
    if kit is None:
        return redirect(url_for('admin.material_kits_list'))

    sku = (request.form.get('sku') or '').strip()
    quantity_raw = (request.form.get('quantity') or '').strip()

    if not sku or not quantity_raw:
        flash('Оберіть позицію з каталогу і вкажіть кількість', 'error')
        return redirect(url_for('admin.material_kit_edit', kit_id=kit.id))
    try:
        quantity = int(quantity_raw)
    except ValueError:
        flash('Кількість має бути цілим числом', 'error')
        return redirect(url_for('admin.material_kit_edit', kit_id=kit.id))
    if quantity <= 0:
        flash('Кількість має бути більшою за нуль', 'error')
        return redirect(url_for('admin.material_kit_edit', kit_id=kit.id))
    if any(item.sku == sku for item in kit.items):
        flash('Ця позиція вже є в комплекті', 'error')
        return redirect(url_for('admin.material_kit_edit', kit_id=kit.id))

    # name_snapshot фіксується на МОМЕНТ додавання -- так історія комплекту
    # лишається читабельною, навіть якщо каталог MM Medic перейменує товар
    # пізніше. Форма шле його прихованим полем разом з вибором; якщо його
    # немає (напр. форма надіслана без JS), шукаємо в каталозі як fallback.
    name_snapshot = (request.form.get('name_snapshot') or '').strip() or None
    if not name_snapshot:
        catalog, _err, _stale = mrs.get_catalog(consumable=True)
        name_snapshot = next(
            (c.get('name') for c in catalog if c.get('sku') == sku), None,
        )

    item = MaterialKitItem(
        kit_id=kit.id,
        sku=sku,
        name_snapshot=name_snapshot,
        quantity=quantity,
        is_required=bool(request.form.get('is_required')),
        note=(request.form.get('note') or '').strip() or None,
    )
    db.session.add(item)
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s added item %s x%s to material kit #%s',
            current_user.email, sku, quantity, kit.id,
        )
        flash('Позицію додано', 'success')
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to add item to material kit #%s', kit_id)
        flash('Помилка при додаванні позиції', 'error')
    return redirect(url_for('admin.material_kit_edit', kit_id=kit.id))


@admin_bp.route('/material-kits/<int:kit_id>/items/<int:item_id>/delete', methods=['POST'])
@admin_required
def material_kit_item_delete(kit_id, item_id):
    item = MaterialKitItem.query.filter_by(id=item_id, kit_id=kit_id).first()
    if not item:
        flash('Позицію не знайдено', 'error')
        return redirect(url_for('admin.material_kit_edit', kit_id=kit_id))

    db.session.delete(item)
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s removed item #%s (%s) from material kit #%s',
            current_user.email, item_id, item.sku, kit_id,
        )
        flash('Позицію видалено', 'success')
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to delete item #%s', item_id)
        flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.material_kit_edit', kit_id=kit_id))
