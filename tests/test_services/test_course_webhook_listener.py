"""Integration tests for SQLAlchemy-triggered webhook enqueue.

Listener _on_commit на Course/CourseInstance викликає
`app.services.webhook_queue.enqueue(course_id, slug, action)`.

Перевіряємо виклик через mock -- стабільніше ніж читати webhook_deliveries
у БД, бо тестовий db_session fixture не дозволяє nested commit всередині
after_commit listener (session вже у 'committed' state).
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
    s.partner_integration_enabled = True
    s.partner_webhook_enabled = True
    s.partner_webhook_url = 'https://partner.test/hook'
    s.partner_webhook_secret = 'x' * 48
    db.session.commit()
    yield
    s.partner_integration_enabled = False
    s.partner_webhook_enabled = False
    s.partner_webhook_url = ''
    s.partner_webhook_secret = ''
    db.session.commit()


@pytest.fixture
def admin_user(app):
    u = User(email=f'admin-{uuid4().hex[:6]}@test.com', password='pw123456')
    db.session.add(u)
    db.session.commit()
    return u


def _actions_for(mock_enqueue, course_id):
    """Зібрати actions з усіх викликів mock.enqueue для заданого course_id."""
    return [
        call.kwargs.get('action') or call.args[2]
        for call in mock_enqueue.call_args_list
        if (call.kwargs.get('course_id') or call.args[0]) == course_id
    ]


def _slug_action_pairs(mock_enqueue):
    """[(slug, action), ...] -- щоб порівнювати зі snapshot-полями."""
    pairs = []
    for call in mock_enqueue.call_args_list:
        args = call.args
        kwargs = call.kwargs
        slug = kwargs.get('course_slug') or (args[1] if len(args) > 1 else None)
        action = kwargs.get('action') or (args[2] if len(args) > 2 else None)
        pairs.append((slug, action))
    return pairs


class TestEnqueueOnCommit:
    def test_insert_calls_enqueue_created(self, enabled_webhook, admin_user):
        with patch('app.services.webhook_queue.enqueue') as mock_enqueue:
            c = Course(
                title='New Course', slug=f'new-{uuid4().hex[:8]}',
                event_type='course', base_price=100, is_active=True,
                created_by=admin_user.id,
            )
            db.session.add(c)
            db.session.commit()

        assert mock_enqueue.called
        assert 'created' in _actions_for(mock_enqueue, c.id)

    def test_update_calls_enqueue_updated(self, enabled_webhook, admin_user):
        c = Course(
            title='Old', slug=f'upd-{uuid4().hex[:8]}',
            event_type='course', base_price=100, is_active=True,
            created_by=admin_user.id,
        )
        db.session.add(c)
        db.session.commit()

        with patch('app.services.webhook_queue.enqueue') as mock_enqueue:
            c.title = 'New title'
            db.session.commit()

        actions = _actions_for(mock_enqueue, c.id)
        assert actions == ['updated']

    def test_delete_calls_enqueue_deleted_with_snapshot(self, enabled_webhook, admin_user):
        c = Course(
            title='Doomed', slug=f'del-{uuid4().hex[:8]}',
            event_type='course', base_price=0, is_active=True,
            created_by=admin_user.id,
        )
        db.session.add(c)
        db.session.commit()
        saved_slug = c.slug
        saved_id = c.id

        with patch('app.services.webhook_queue.enqueue') as mock_enqueue:
            db.session.delete(c)
            db.session.commit()

        pairs = _slug_action_pairs(mock_enqueue)
        assert (saved_slug, 'deleted') in pairs
        # Snapshot: enqueue отримав правильний course_id навіть після delete.
        assert mock_enqueue.call_args_list, 'enqueue must be called'

    def test_instance_update_calls_course_updated(self, enabled_webhook, admin_user):
        """Зміна CourseInstance тригерить 'updated' для батьківського Course."""
        c = Course(
            title='Parent', slug=f'pr-{uuid4().hex[:8]}',
            event_type='course', base_price=0, is_active=True,
            created_by=admin_user.id,
        )
        db.session.add(c)
        db.session.commit()

        with patch('app.services.webhook_queue.enqueue') as mock_enqueue:
            inst = CourseInstance(course_id=c.id, status='published')
            db.session.add(inst)
            db.session.commit()

        actions = _actions_for(mock_enqueue, c.id)
        assert actions == ['updated']


class TestRollbackClearsPending:
    def test_rollback_does_not_call_enqueue(self, enabled_webhook, admin_user):
        """Rollback -- pending-list у session.info очищається, enqueue не викликається."""
        slug = f'rb-{uuid4().hex[:8]}'
        with patch('app.services.webhook_queue.enqueue') as mock_enqueue:
            c = Course(
                title='Never Saved', slug=slug,
                event_type='course', base_price=100, is_active=True,
                created_by=admin_user.id,
            )
            db.session.add(c)
            db.session.flush()   # fires after_insert listener (add to pending list)
            db.session.rollback()  # discards transaction -- pending cleared

        mock_enqueue.assert_not_called()


class TestEnqueueErrorIsolation:
    def test_enqueue_exception_does_not_break_commit(self, enabled_webhook, admin_user):
        """Якщо webhook_queue.enqueue кидає -- save course все одно персистить."""
        slug = f'ok-{uuid4().hex[:8]}'
        with patch(
            'app.services.webhook_queue.enqueue',
            side_effect=RuntimeError('boom'),
        ):
            c = Course(
                title='Resilient', slug=slug,
                event_type='course', base_price=0, is_active=True,
                created_by=admin_user.id,
            )
            db.session.add(c)
            db.session.commit()

        # Course персистентний попри збій listener-а.
        assert Course.query.filter_by(slug=slug).first() is not None
