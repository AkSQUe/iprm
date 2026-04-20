"""Admin: перегляд та управління чергою партнерських webhook-ів."""
import logging
from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user

from app.admin import admin_bp
from app.admin._helpers import try_commit
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.webhook_delivery import WebhookDelivery

audit_logger = logging.getLogger('audit')


@admin_bp.route('/webhooks')
@admin_required
def webhooks_list():
    filter_status = request.args.get('status', '')

    query = WebhookDelivery.query
    if filter_status:
        query = query.filter(WebhookDelivery.status == filter_status)

    deliveries = query.order_by(WebhookDelivery.created_at.desc()).limit(200).all()

    counts = dict(
        db.session.query(
            WebhookDelivery.status,
            db.func.count(WebhookDelivery.id),
        )
        .group_by(WebhookDelivery.status)
        .all()
    )

    return render_template(
        'admin/webhooks.html',
        deliveries=deliveries,
        counts=counts,
        filter_status=filter_status,
    )


@admin_bp.route('/webhooks/<int:delivery_id>/retry', methods=['POST'])
@admin_required
def webhook_retry(delivery_id):
    """Переставити рядок у pending і негайно спробувати відправити."""
    delivery = db.session.get(WebhookDelivery, delivery_id)
    if not delivery:
        flash('Запис не знайдено', 'error')
        return redirect(url_for('admin.webhooks_list'))

    # Reset до pending -- scheduler worker підхопить за хвилину.
    delivery.status = 'pending'
    delivery.next_retry_at = datetime.now(timezone.utc)
    delivery.last_error = None

    if try_commit(log_context=f'webhook_retry id={delivery_id}'):
        audit_logger.info(
            'Admin %s queued retry for webhook_delivery %s',
            current_user.email, delivery_id,
        )
        # Одразу запускаємо worker (не чекаємо cron-тик)
        try:
            from app.services.webhook_queue import process_queue
            process_queue()
        except Exception:
            logging.getLogger(__name__).exception('Immediate retry failed')
        flash('Запит на повтор відправки поставлено', 'success')
    return redirect(url_for('admin.webhooks_list'))


@admin_bp.route('/webhooks/<int:delivery_id>/delete', methods=['POST'])
@admin_required
def webhook_delete(delivery_id):
    delivery = db.session.get(WebhookDelivery, delivery_id)
    if not delivery:
        flash('Запис не знайдено', 'error')
        return redirect(url_for('admin.webhooks_list'))

    db.session.delete(delivery)
    if try_commit(
        log_context=f'webhook_delete id={delivery_id}',
        error_msg='Помилка при видаленні',
    ):
        audit_logger.info(
            'Admin %s deleted webhook_delivery %s',
            current_user.email, delivery_id,
        )
        flash('Запис видалено', 'success')
    return redirect(url_for('admin.webhooks_list'))
