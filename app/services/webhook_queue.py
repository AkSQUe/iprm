"""Webhook queue worker.

Читає pending + retrying рядки з `webhook_deliveries` і відправляє їх через
dispatch_one. Реалізує:
    * Exponential backoff на transient failures (1, 2, 4, 8, 16 хв)
    * Circuit breaker: після N послідовних transient-помилок усієї черги
      пауза на CIRCUIT_PAUSE_SECONDS
    * Max attempts: після MAX_ATTEMPTS спроб рядок переходить у 'failed'

Викликається з APScheduler (every 1 min) або вручну з адмінки.
"""
import logging
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.webhook_delivery import (
    INITIAL_BACKOFF_SECONDS,
    MAX_ATTEMPTS,
    WebhookDelivery,
)
from app.services.webhook_dispatcher import dispatch_one, dispatch_partner_event

logger = logging.getLogger(__name__)

# Максимум скільки рядків обробити за один прогін (захист від довгих job-ів)
BATCH_LIMIT = 25

# Circuit breaker: якщо >= 5 послідовних transient failures у одному прогіні,
# ставимо паузу на 10 хв щоб партнер міг відновитися.
CIRCUIT_CONSECUTIVE_FAILURES = 5
CIRCUIT_PAUSE_SECONDS = 600


def process_queue():
    """Прогін обробки черги. Повертає dict зі статистикою."""
    settings = SiteSettings.get()
    if not settings.partner_integration_enabled:
        return {'skipped': 'integration disabled', 'sent': 0, 'failed': 0, 'retrying': 0}
    if not settings.partner_webhook_enabled:
        return {'skipped': 'webhook disabled', 'sent': 0, 'failed': 0, 'retrying': 0}

    secret = settings.partner_webhook_secret
    if not secret:
        logger.warning('webhook_queue: secret not configured -- skipping')
        return {'skipped': 'no secret', 'sent': 0, 'failed': 0, 'retrying': 0}

    now = datetime.now(timezone.utc)
    # Pending (ніколи не пробувалися) + retrying де next_retry_at прийшов
    candidates = (
        WebhookDelivery.query
        .filter(
            db.or_(
                WebhookDelivery.status == 'pending',
                db.and_(
                    WebhookDelivery.status == 'retrying',
                    WebhookDelivery.next_retry_at <= now,
                ),
            )
        )
        .order_by(WebhookDelivery.created_at.asc())
        .limit(BATCH_LIMIT)
        .all()
    )

    stats = {'sent': 0, 'failed': 0, 'retrying': 0, 'processed': 0}
    consecutive_transient = 0

    for delivery in candidates:
        if consecutive_transient >= CIRCUIT_CONSECUTIVE_FAILURES:
            logger.warning(
                'webhook_queue: circuit breaker triggered '
                '(%d consecutive transient fails); pausing remaining %d',
                consecutive_transient, len(candidates) - stats['processed'],
            )
            # Залишок рядків відкладаємо на CIRCUIT_PAUSE_SECONDS.
            _pause_remaining(candidates[stats['processed']:])
            break

        stats['processed'] += 1
        delivery.attempts += 1

        # Дві форми доставки в одній черзі: каталожне «перечитай курс» і
        # партнерська подія з власним часом. Ретраї, backoff і circuit
        # breaker у них спільні — саме тому черга одна.
        if delivery.is_partner_event:
            result = dispatch_partner_event(
                event_type=delivery.event_type,
                payload=delivery.payload,
                target_url=delivery.target_url,
                secret=secret,
                event_uuid=delivery.event_uuid,
            )
        else:
            result = dispatch_one(
                course_id=delivery.course_id,
                course_slug=delivery.course_slug,
                action=delivery.action,
                target_url=delivery.target_url,
                secret=secret,
                event_uuid=delivery.event_uuid,
            )

        if result.ok:
            delivery.status = 'sent'
            delivery.sent_at = datetime.now(timezone.utc)
            delivery.last_http_status = result.http_status
            delivery.last_error = None
            delivery.next_retry_at = None
            stats['sent'] += 1
            consecutive_transient = 0
            logger.info(
                'webhook_delivery id=%s sent course=%s action=%s',
                delivery.id, delivery.course_slug, delivery.action,
            )
        elif result.retryable and delivery.attempts < MAX_ATTEMPTS:
            delivery.status = 'retrying'
            delivery.last_http_status = result.http_status
            delivery.last_error = result.error
            delivery.next_retry_at = _compute_next_retry(delivery.attempts)
            stats['retrying'] += 1
            consecutive_transient += 1
            logger.warning(
                'webhook_delivery id=%s retry %d/%d course=%s action=%s err=%s',
                delivery.id, delivery.attempts, MAX_ATTEMPTS,
                delivery.course_slug, delivery.action, result.error,
            )
        else:
            delivery.status = 'failed'
            delivery.last_http_status = result.http_status
            delivery.last_error = result.error
            delivery.next_retry_at = None
            stats['failed'] += 1
            consecutive_transient = 0  # permanent, не transient
            logger.error(
                'webhook_delivery id=%s FAILED course=%s action=%s attempts=%d err=%s',
                delivery.id, delivery.course_slug, delivery.action,
                delivery.attempts, result.error,
            )

        db.session.commit()

    return stats


def _compute_next_retry(attempts):
    """Exponential backoff: 1, 2, 4, 8, 16 хв (початкова база 60s)."""
    seconds = INITIAL_BACKOFF_SECONDS * (2 ** (attempts - 1))
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _pause_remaining(remaining):
    """При спрацьованому circuit breaker відкладаємо останні рядки."""
    pause_until = datetime.now(timezone.utc) + timedelta(seconds=CIRCUIT_PAUSE_SECONDS)
    for delivery in remaining:
        if delivery.status == 'pending':
            delivery.status = 'retrying'
        delivery.next_retry_at = pause_until
    db.session.commit()


def enqueue(course_id, course_slug, action):
    """Helper: створити новий WebhookDelivery-рядок у pending-статусі.

    Викликається з course_webhook_listener._on_commit -- тобто ПІСЛЯ коміту
    основної транзакції, коли db.session ще у 'committed'-стані і SQLAlchemy
    забороняє їй виконувати SQL (InvalidRequestError). Тому всі запити тут
    йдуть через ОКРЕМУ короткоживучу сесію на тому ж engine.

    Snapshot target_url на момент вставки, щоб зміна налаштувань не впливала
    на pending-рядки. Повертає id створеного рядка або None.
    """
    import uuid

    from sqlalchemy.orm import Session

    with Session(db.engine) as session:
        # Не SiteSettings.get(): get-or-create прив'язаний до db.session,
        # а нам потрібне читання саме у цій сесії. Рядка немає -- інтеграцію
        # ще не конфігурували, сповіщати нікуди.
        settings = session.get(SiteSettings, 1)
        if settings is None:
            return None
        if not settings.partner_integration_enabled or not settings.partner_webhook_enabled:
            return None
        target_url = (settings.partner_webhook_url or '').strip()
        if not target_url:
            return None

        delivery = WebhookDelivery(
            course_id=course_id,
            course_slug=course_slug,
            action=action,
            event_uuid=uuid.uuid4().hex,
            target_url=target_url,
            status='pending',
        )
        session.add(delivery)
        try:
            session.commit()
            return delivery.id
        except Exception:
            session.rollback()
            current_app.logger.exception(
                'Failed to enqueue webhook course=%s action=%s', course_slug, action,
            )
            return None


def enqueue_partner_event(event_type, payload):
    """Поставити партнерську подію в чергу доставки.

    Окрема коротка сесія з тієї ж причини, що й у ``enqueue``: викликається
    після коміту основної транзакції, а іноді — із фонового потоку відправки
    листів, де сесія застосунку вже закрита.

    Адреса береться з ``mm_medic_api_base_url`` (той самий базовий URL, що й
    у клієнта резервувань) і фіксується в рядку: зміна налаштувань не має
    переписувати вже поставлені в чергу події.

    Повертає id рядка або ``None``, якщо слати нікуди. ``None`` — не помилка:
    інтеграція може бути просто вимкнена.
    """
    import uuid

    from sqlalchemy.orm import Session

    with Session(db.engine) as session:
        settings = session.get(SiteSettings, 1)
        if settings is None:
            return None
        if not settings.partner_integration_enabled:
            return None
        if not getattr(settings, 'mm_medic_integration_enabled', False):
            return None

        base_url = (settings.mm_medic_api_base_url or '').strip().rstrip('/')
        if not base_url:
            return None

        delivery = WebhookDelivery(
            event_type=event_type,
            payload=payload or {},
            event_uuid=uuid.uuid4().hex,
            target_url=f'{base_url}/api/partner/iprm/events',
            status='pending',
        )
        session.add(delivery)
        try:
            session.commit()
            return delivery.id
        except Exception:
            session.rollback()
            current_app.logger.exception(
                'Failed to enqueue partner event %s', event_type,
            )
            return None
