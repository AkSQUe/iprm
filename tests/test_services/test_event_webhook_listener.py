"""Integration tests for SQLAlchemy-triggered webhook dispatch."""
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.event import Event
from app.models.site_settings import SiteSettings
from app.models.user import User


@pytest.fixture
def enabled_webhook(app):
    s = SiteSettings.get()
    s.partner_webhook_enabled = True
    s.partner_webhook_url = 'https://partner.test/hook'
    s.partner_webhook_secret = 'x' * 48
    db.session.commit()
    yield
    s.partner_webhook_enabled = False
    db.session.commit()


@pytest.fixture
def admin_user(app):
    u = User(email=f'admin-{uuid4().hex[:6]}@test.com', password='pw123456')
    db.session.add(u)
    db.session.commit()
    return u


class TestListenerFiresOnCommit:
    def test_insert_triggers_webhook(self, enabled_webhook, admin_user):
        with patch('app.services.event_webhook_listener.dispatch_event_webhook') as mock:
            ev = Event(
                title='New Course', slug=f'new-{uuid4().hex[:8]}',
                event_type='course', event_format='online', status='published',
                price=100, is_active=True, created_by=admin_user.id,
            )
            db.session.add(ev)
            db.session.commit()

        assert mock.called
        _, _, action = mock.call_args.args
        assert action == 'created'

    def test_update_triggers_webhook(self, enabled_webhook, admin_user):
        ev = Event(
            title='Old', slug=f'upd-{uuid4().hex[:8]}',
            event_type='course', event_format='online', status='published',
            price=100, is_active=True, created_by=admin_user.id,
        )
        db.session.add(ev)
        db.session.commit()

        with patch('app.services.event_webhook_listener.dispatch_event_webhook') as mock:
            ev.title = 'New title'
            db.session.commit()

        assert mock.called
        assert mock.call_args.args[2] == 'updated'

    def test_delete_triggers_webhook_with_snapshot(self, enabled_webhook, admin_user):
        ev = Event(
            title='Doomed', slug=f'del-{uuid4().hex[:8]}',
            event_type='course', event_format='online', status='draft',
            price=0, is_active=True, created_by=admin_user.id,
        )
        db.session.add(ev)
        db.session.commit()
        saved_slug = ev.slug
        saved_id = ev.id

        with patch('app.services.event_webhook_listener.dispatch_event_webhook') as mock:
            db.session.delete(ev)
            db.session.commit()

        assert mock.called
        event_id, event_slug, action = mock.call_args.args
        assert action == 'deleted'
        assert event_slug == saved_slug  # slug captured before delete
        assert event_id == saved_id

    def test_rollback_does_not_fire_webhook(self, enabled_webhook, admin_user):
        with patch('app.services.event_webhook_listener.dispatch_event_webhook') as mock:
            ev = Event(
                title='Never Saved', slug=f'rb-{uuid4().hex[:8]}',
                event_type='course', event_format='online', status='published',
                price=100, is_active=True, created_by=admin_user.id,
            )
            db.session.add(ev)
            db.session.flush()  # triggers after_insert
            db.session.rollback()  # but no commit — webhook pending gets cleared

        mock.assert_not_called()

    def test_dispatcher_failure_does_not_break_commit(self, enabled_webhook, admin_user):
        """If webhook POST fails mid-dispatch, the event save must still persist."""
        with patch(
            'app.services.event_webhook_listener.dispatch_event_webhook',
            side_effect=RuntimeError('boom'),
        ):
            ev = Event(
                title='Resilient', slug=f'ok-{uuid4().hex[:8]}',
                event_type='course', event_format='online', status='published',
                price=0, is_active=True, created_by=admin_user.id,
            )
            db.session.add(ev)
            db.session.commit()

        # Event persisted despite dispatcher crash.
        assert Event.query.filter_by(id=ev.id).first() is not None
