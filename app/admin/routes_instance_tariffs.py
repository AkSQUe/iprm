"""Admin CRUD тарифів проведення (тарифна вилка, E1 фаза 2)."""
import logging

from flask import render_template, redirect, url_for, flash, request

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import InstanceTariffForm
from app.extensions import db
from flask_login import current_user

from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff

audit_logger = logging.getLogger('audit')


def _instance_or_redirect(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
    return instance


@admin_bp.route('/instances/<int:instance_id>/tariffs', methods=['GET', 'POST'])
@admin_required
def instance_tariffs(instance_id):
    """Список тарифів проведення + форма додавання нового."""
    instance = _instance_or_redirect(instance_id)
    if not instance:
        return redirect(url_for('admin.instances_list'))

    form = InstanceTariffForm()
    form.event_format.choices = InstanceTariff.FORMAT_CHOICES
    if form.validate_on_submit():
        tariff = InstanceTariff(
            instance_id=instance.id,
            name=form.name.data.strip(),
            price=form.price.data,
            description=(form.description.data or '').strip() or None,
            event_format=form.event_format.data or None,
            sort_order=form.sort_order.data if form.sort_order.data is not None else 0,
            is_active=form.is_active.data,
        )
        db.session.add(tariff)
        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s added tariff "%s" (%s) to instance %s',
                current_user.email, tariff.name, tariff.price, instance.id,
            )
            flash('Тариф додано', 'success')
            return redirect(url_for('admin.instance_tariffs', instance_id=instance.id))
        except Exception:
            db.session.rollback()
            audit_logger.exception('Failed to add tariff for instance %s', instance_id)
            flash('Помилка при збереженні', 'error')

    return render_template(
        'admin/instance_tariffs.html',
        instance=instance,
        form=form,
        edit_tariff=None,
    )


@admin_bp.route('/tariffs/<int:tariff_id>/edit', methods=['GET', 'POST'])
@admin_required
def instance_tariff_edit(tariff_id):
    tariff = db.session.get(InstanceTariff, tariff_id)
    if not tariff:
        flash('Тариф не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))
    instance = tariff.instance

    form = InstanceTariffForm(obj=tariff)
    form.event_format.choices = InstanceTariff.FORMAT_CHOICES
    if form.validate_on_submit():
        tariff.name = form.name.data.strip()
        tariff.price = form.price.data
        tariff.description = (form.description.data or '').strip() or None
        tariff.event_format = form.event_format.data or None
        tariff.sort_order = form.sort_order.data if form.sort_order.data is not None else 0
        tariff.is_active = form.is_active.data
        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s updated tariff #%s ("%s") of instance %s',
                current_user.email, tariff.id, tariff.name, instance.id,
            )
            flash('Тариф оновлено', 'success')
            return redirect(url_for('admin.instance_tariffs', instance_id=instance.id))
        except Exception:
            db.session.rollback()
            audit_logger.exception('Failed to update tariff #%s', tariff_id)
            flash('Помилка при збереженні', 'error')

    return render_template(
        'admin/instance_tariffs.html',
        instance=instance,
        form=form,
        edit_tariff=tariff,
    )


@admin_bp.route('/tariffs/<int:tariff_id>/delete', methods=['POST'])
@admin_required
def instance_tariff_delete(tariff_id):
    tariff = db.session.get(InstanceTariff, tariff_id)
    if not tariff:
        flash('Тариф не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))
    instance_id = tariff.instance_id
    name = tariff.name

    db.session.delete(tariff)
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s deleted tariff #%s ("%s") of instance %s',
            current_user.email, tariff_id, name, instance_id,
        )
        flash('Тариф видалено', 'success')
    except Exception:
        db.session.rollback()
        audit_logger.exception('Failed to delete tariff #%s', tariff_id)
        flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.instance_tariffs', instance_id=instance_id))
