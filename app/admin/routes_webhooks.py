"""Admin: перегляд та управління чергою партнерських webhook-ів."""
import logging
from datetime import datetime, timezone

from flask import render_template, flash, request
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.admin._helpers import try_commit
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.webhook_delivery import MAX_ATTEMPTS, WebhookDelivery

audit_logger = logging.getLogger('audit')

# action -- окреме поле фільтра (не статус доставки): яку зміну курсу
# зловив listener. Значення звірені з ck_webhook_deliveries_action у моделі.
_ACTION_CHOICES = {'created': 'Створення', 'updated': 'Оновлення', 'deleted': 'Видалення'}


def _event_type_choices():
    """Перелік event_type із черги + 'catalog' для каталожних подій.

    Каталожні події (зміна/видалення курсу) старого формату лишають
    event_type порожнім -- у переліку фільтра їм відповідає окрема
    синтетична опція, бо в БД такого значення немає.
    """
    rows = (
        db.session.query(WebhookDelivery.event_type)
        .filter(WebhookDelivery.event_type.isnot(None), WebhookDelivery.event_type != '')
        .distinct()
        .order_by(WebhookDelivery.event_type)
        .all()
    )
    choices = {'catalog': 'Каталог (курси)'}
    for (event_type,) in rows:
        choices[event_type] = event_type
    return choices


def _status_arg():
    """Зріз статусу: звірка з бейджами моделі, невідоме падає в '' (усі)."""
    return _listing.choice_arg('status', WebhookDelivery.STATUS_BADGES)


def _filters(event_type_choices=None):
    """Фільтри реєстру -- спільні для списку й для `_back()`."""
    if event_type_choices is None:
        event_type_choices = _event_type_choices()
    return {
        'q': _listing.text_arg('q'),
        'event_type': _listing.choice_arg('event_type', event_type_choices),
        'action': _listing.choice_arg('action', _ACTION_CHOICES),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _back():
    """Безпечний редірект назад до списку зі збереженням поточного зрізу.

    Спільний `_listing.back_redirect` перечитує й перевіряє кожен параметр
    зрізу тим самим способом, що й роут списку (НЕ request.referrer -- той
    керований клієнтом і відкриває open redirect). Джерело значень -- query
    string самого запиту дії (retry/delete): рядкові форми несуть зріз у
    action-URL через `back_args`, прихованих полів тут немає.
    """
    return _listing.back_redirect(
        'admin.webhooks_list', _filters(), {'status': _status_arg()},
    )


@admin_bp.route('/webhooks')
@admin_required
def webhooks_list():
    filter_status = _status_arg()
    event_type_choices = _event_type_choices()
    filters = _filters(event_type_choices)

    query = WebhookDelivery.query
    if filter_status:
        query = query.filter(WebhookDelivery.status == filter_status)
    query = _listing.apply_search(query, filters['q'], [
        WebhookDelivery.event_uuid, WebhookDelivery.course_slug,
        WebhookDelivery.target_url, WebhookDelivery.last_error,
    ])
    if filters['event_type'] == 'catalog':
        query = query.filter(db.or_(
            WebhookDelivery.event_type.is_(None),
            WebhookDelivery.event_type == '',
        ))
    elif filters['event_type']:
        query = query.filter(WebhookDelivery.event_type == filters['event_type'])
    if filters['action']:
        query = query.filter(WebhookDelivery.action == filters['action'])
    query = _listing.apply_date_range(
        query, WebhookDelivery.created_at, filters['date_from'], filters['date_to'],
    )
    pagination = query.order_by(WebhookDelivery.created_at.desc()).paginate(
        page=request.args.get('page', 1, type=int),
        per_page=_listing.per_page_arg(), error_out=False,
    )

    # Черга рахується по ВСІЙ таблиці -- це розмір черги, а не поточного зрізу.
    counts = dict(
        db.session.query(
            WebhookDelivery.status,
            db.func.count(WebhookDelivery.id),
        )
        .group_by(WebhookDelivery.status)
        .all()
    )

    filter_args = _listing.filter_args(filters)
    back_args = _listing.back_args(filter_args, pagination.page, {'status': filter_status})

    return render_template(
        'admin/webhooks.html',
        deliveries=pagination.items,
        pagination=pagination,
        counts=counts,
        filter_status=filter_status,
        filters=filters,
        filter_args=filter_args,
        back_args=back_args,
        event_type_options=list(event_type_choices.items()),
        action_options=list(_ACTION_CHOICES.items()),
        per_page_options=_listing.PER_PAGE_OPTIONS,
        max_attempts=MAX_ATTEMPTS,
    )


@admin_bp.route('/webhooks/<int:delivery_id>/retry', methods=['POST'])
@admin_required
def webhook_retry(delivery_id):
    """Переставити рядок у pending і негайно спробувати відправити."""
    delivery = db.session.get(WebhookDelivery, delivery_id)
    if not delivery:
        flash('Запис не знайдено', 'error')
        return _back()

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
    return _back()


@admin_bp.route('/webhooks/<int:delivery_id>/delete', methods=['POST'])
@admin_required
def webhook_delete(delivery_id):
    delivery = db.session.get(WebhookDelivery, delivery_id)
    if not delivery:
        flash('Запис не знайдено', 'error')
        return _back()

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
    return _back()
