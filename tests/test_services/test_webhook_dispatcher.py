"""Tests for webhook_dispatcher.dispatch_event_webhook."""
import hashlib
import hmac
import json
from unittest.mock import patch, MagicMock

import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.services.webhook_dispatcher import dispatch_event_webhook


SECRET = 'test-webhook-secret-' + 'x' * 40


@pytest.fixture
def enabled_webhook(app):
    s = SiteSettings.get()
    s.partner_webhook_enabled = True
    s.partner_webhook_url = 'https://partner.test/api/webhooks/iprm/events'
    s.partner_webhook_secret = SECRET
    db.session.commit()
    yield s
    s.partner_webhook_enabled = False
    s.partner_webhook_url = ''
    s.partner_webhook_secret = ''
    db.session.commit()


class TestDispatch:
    def test_posts_signed_payload(self, enabled_webhook):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            dispatch_event_webhook(event_id=42, event_slug='course-x', action='updated')

        assert mock_post.called
        call = mock_post.call_args
        # url is positional arg 0
        assert call.args[0] == 'https://partner.test/api/webhooks/iprm/events'
        body = call.kwargs['data']  # bytes
        headers = call.kwargs['headers']

        # Signature must match HMAC-SHA256(body, secret)
        expected_sig = hmac.new(
            SECRET.encode('utf-8'), body, hashlib.sha256,
        ).hexdigest()
        assert headers['X-IPRM-Signature'] == expected_sig

        # Idempotency key present
        assert 'X-IPRM-Event-Id' in headers
        assert len(headers['X-IPRM-Event-Id']) >= 16

        # Payload shape
        payload = json.loads(body)
        assert payload['event_type'] == 'event.updated'
        assert payload['slug'] == 'course-x'
        assert payload['event_id'] == 42
        assert payload['timestamp']

    def test_noop_when_disabled(self, app):
        s = SiteSettings.get()
        s.partner_webhook_enabled = False
        db.session.commit()
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            dispatch_event_webhook(1, 'x', 'created')
        mock_post.assert_not_called()

    def test_noop_when_url_missing(self, app):
        s = SiteSettings.get()
        s.partner_webhook_enabled = True
        s.partner_webhook_url = ''
        s.partner_webhook_secret = SECRET
        db.session.commit()
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            dispatch_event_webhook(1, 'x', 'created')
        mock_post.assert_not_called()
        s.partner_webhook_enabled = False
        db.session.commit()

    def test_never_raises_on_http_error(self, enabled_webhook):
        """Event.save() must succeed even if partner is down."""
        import requests
        with patch(
            'app.services.webhook_dispatcher.requests.post',
            side_effect=requests.ConnectionError('partner offline'),
        ):
            # Must not raise.
            dispatch_event_webhook(1, 'x', 'created')

    def test_never_raises_on_5xx_response(self, enabled_webhook):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=False, status_code=503, text='down')
            dispatch_event_webhook(1, 'x', 'updated')

    def test_action_event_type_format(self, enabled_webhook):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            dispatch_event_webhook(1, 'x', 'deleted')
        payload = json.loads(mock_post.call_args.kwargs['data'])
        assert payload['event_type'] == 'event.deleted'
