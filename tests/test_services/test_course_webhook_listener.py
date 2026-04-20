"""Integration tests for SQLAlchemy-triggered webhook dispatch.

Listener слухає Course та CourseInstance (див. course_webhook_listener).
"""
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
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
        with patch('app.services.course_webhook_listener.dispatch_event_webhook') as mock:
            c = Course(
                title='New Course', slug=f'new-{uuid4().hex[:8]}',
                event_type='course', base_price=100, is_active=True,
                created_by=admin_user.id,
            )
            db.session.add(c)
            db.session.commit()

        assert mock.called
        _, _, action = mock.call_args.args
        assert action == 'created'

    def test_update_triggers_webhook(self, enabled_webhook, admin_user):
        c = Course(
            title='Old', slug=f'upd-{uuid4().hex[:8]}',
            event_type='course', base_price=100, is_active=True,
            created_by=admin_user.id,
        )
        db.session.add(c)
        db.session.commit()

        with patch('app.services.course_webhook_listener.dispatch_event_webhook') as mock:
            c.title = 'New title'
            db.session.commit()

        assert mock.called
        assert mock.call_args.args[2] == 'updated'

    def test_delete_triggers_webhook_with_snapshot(self, enabled_webhook, admin_user):
        c = Course(
            title='Doomed', slug=f'del-{uuid4().hex[:8]}',
            event_type='course', base_price=0, is_active=True,
            created_by=admin_user.id,
        )
        db.session.add(c)
        db.session.commit()
        saved_slug = c.slug
        saved_id = c.id

        with patch('app.services.course_webhook_listener.dispatch_event_webhook') as mock:
            db.session.delete(c)
            db.session.commit()

        assert mock.called
        course_id, course_slug, action = mock.call_args.args
        assert action == 'deleted'
        assert course_slug == saved_slug  # slug captured before delete
        assert course_id == saved_id

    def test_instance_update_triggers_course_webhook(self, enabled_webhook, admin_user):
        """Зміна CourseInstance тригерить 'updated' webhook для батьківського Course."""
        c = Course(
            title='Parent', slug=f'pr-{uuid4().hex[:8]}',
            event_type='course', base_price=0, is_active=True,
            created_by=admin_user.id,
        )
        db.session.add(c)
        db.session.commit()

        with patch('app.services.course_webhook_listener.dispatch_event_webhook') as mock:
            inst = CourseInstance(course_id=c.id, status='published')
            db.session.add(inst)
            db.session.commit()

        assert mock.called
        course_id, course_slug, action = mock.call_args.args
        assert action == 'updated'
        assert course_id == c.id

    def test_rollback_does_not_fire_webhook(self, enabled_webhook, admin_user):
        with patch('app.services.course_webhook_listener.dispatch_event_webhook') as mock:
            c = Course(
                title='Never Saved', slug=f'rb-{uuid4().hex[:8]}',
                event_type='course', base_price=100, is_active=True,
                created_by=admin_user.id,
            )
            db.session.add(c)
            db.session.flush()  # triggers after_insert
            db.session.rollback()  # no commit — pending cleared

        mock.assert_not_called()

    def test_dispatcher_failure_does_not_break_commit(self, enabled_webhook, admin_user):
        """Якщо webhook POST падає -- save course має пройти успішно."""
        with patch(
            'app.services.course_webhook_listener.dispatch_event_webhook',
            side_effect=RuntimeError('boom'),
        ):
            c = Course(
                title='Resilient', slug=f'ok-{uuid4().hex[:8]}',
                event_type='course', base_price=0, is_active=True,
                created_by=admin_user.id,
            )
            db.session.add(c)
            db.session.commit()

        assert Course.query.filter_by(id=c.id).first() is not None
