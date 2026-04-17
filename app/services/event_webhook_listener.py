"""SQLAlchemy listeners that fire partner webhooks after Event changes commit.

Dispatch runs AFTER transaction commit — never inside — so that a failing
webhook cannot rollback the admin's save. Uses session.info to collect
pending dispatches during the transaction, then flushes them on after_commit.

Register once at app startup via `register_event_listeners(db)`.
"""
import logging

from sqlalchemy import event as sa_event

from app.models.event import Event
from app.services.webhook_dispatcher import dispatch_event_webhook

logger = logging.getLogger(__name__)

_PENDING_KEY = '_iprm_webhook_pending'


def _queue(session, event_id, event_slug, action):
    pending = session.info.setdefault(_PENDING_KEY, [])
    pending.append((event_id, event_slug, action))


def register_event_listeners(db) -> None:
    """Attach after_{insert,update,delete} + after_commit hooks to Event."""

    @sa_event.listens_for(Event, 'after_insert')
    def _on_insert(mapper, connection, target):
        session = db.session.object_session(target)
        if session is None:
            session = db.session
        _queue(session, target.id, target.slug, 'created')

    @sa_event.listens_for(Event, 'after_update')
    def _on_update(mapper, connection, target):
        session = db.session.object_session(target)
        if session is None:
            session = db.session
        _queue(session, target.id, target.slug, 'updated')

    @sa_event.listens_for(Event, 'after_delete')
    def _on_delete(mapper, connection, target):
        session = db.session.object_session(target)
        if session is None:
            session = db.session
        # Snapshot id/slug now — row will be gone after commit.
        _queue(session, target.id, target.slug, 'deleted')

    @sa_event.listens_for(db.session, 'after_commit')
    def _on_commit(session):
        pending = session.info.pop(_PENDING_KEY, None)
        if not pending:
            return
        # Dispatch synchronously (fire-and-forget inside dispatcher).
        # If this becomes a latency problem, wrap in threading.Thread or
        # replace with Celery/APScheduler job enqueueing.
        for event_id, event_slug, action in pending:
            try:
                dispatch_event_webhook(event_id, event_slug, action)
            except Exception:
                logger.exception(
                    'Webhook dispatch crashed unexpectedly for %s/%s',
                    action, event_slug,
                )

    @sa_event.listens_for(db.session, 'after_rollback')
    def _on_rollback(session):
        # If the transaction rolled back, no webhook fires.
        session.info.pop(_PENDING_KEY, None)
