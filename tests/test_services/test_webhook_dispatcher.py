"""Tests for webhook_dispatcher.dispatch_one.

Dispatcher -- чистий HTTP-layer: не читає SiteSettings, не пише в DB.
Повертає DispatchResult, який caller (webhook_queue) інтерпретує.
"""
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.webhook_dispatcher import DispatchResult, dispatch_one


SECRET = 'test-webhook-secret-' + 'x' * 40
TARGET_URL = 'https://partner.test/api/webhooks/iprm/events'


def _call(action='updated', course_id=42, course_slug='course-x',
          target_url=TARGET_URL, secret=SECRET, event_uuid='uuid-abc123'):
    return dispatch_one(
        course_id=course_id,
        course_slug=course_slug,
        action=action,
        target_url=target_url,
        secret=secret,
        event_uuid=event_uuid,
    )


class TestSignedPayload:
    def test_posts_to_target_url(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            _call()

        assert mock_post.called
        call = mock_post.call_args
        assert call.args[0] == TARGET_URL

    def test_signature_is_hmac_sha256_of_body(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            _call()

        call = mock_post.call_args
        body = call.kwargs['data']  # bytes
        headers = call.kwargs['headers']
        expected_sig = hmac.new(
            SECRET.encode('utf-8'), body, hashlib.sha256,
        ).hexdigest()
        assert headers['X-IPRM-Signature'] == expected_sig

    def test_event_id_header_is_passed_event_uuid(self):
        """X-IPRM-Event-Id -- stable id між retry (передається caller-ом)."""
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            _call(event_uuid='fixed-uuid-xyz')
        headers = mock_post.call_args.kwargs['headers']
        assert headers['X-IPRM-Event-Id'] == 'fixed-uuid-xyz'

    def test_payload_shape(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            _call(course_id=42, course_slug='course-x', action='updated')

        body = mock_post.call_args.kwargs['data']
        payload = json.loads(body)
        assert payload['event_type'] == 'event.updated'
        assert payload['slug'] == 'course-x'
        assert payload['event_id'] == 42
        assert payload['timestamp']

    def test_action_event_type_format(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            _call(action='deleted')
        payload = json.loads(mock_post.call_args.kwargs['data'])
        assert payload['event_type'] == 'event.deleted'


class TestDispatchResultSuccess:
    def test_2xx_returns_ok(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            result = _call()
        assert isinstance(result, DispatchResult)
        assert result.ok is True
        assert result.retryable is False
        assert result.http_status == 200
        assert result.error is None

    def test_201_returns_ok(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=201)
            result = _call()
        assert result.ok is True
        assert result.http_status == 201


class TestDispatchResultTransient:
    def test_5xx_is_retryable(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=False, status_code=503, text='down')
            result = _call()
        assert result.ok is False
        assert result.retryable is True
        assert result.http_status == 503
        assert 'down' in result.error

    def test_timeout_is_retryable(self):
        with patch(
            'app.services.webhook_dispatcher.requests.post',
            side_effect=requests.Timeout('read timeout'),
        ):
            result = _call()
        assert result.ok is False
        assert result.retryable is True
        assert result.http_status is None
        assert 'timeout' in result.error.lower()

    def test_connection_error_is_retryable(self):
        with patch(
            'app.services.webhook_dispatcher.requests.post',
            side_effect=requests.ConnectionError('partner offline'),
        ):
            result = _call()
        assert result.ok is False
        assert result.retryable is True
        assert result.http_status is None


class TestDispatchResultPermanent:
    def test_4xx_is_not_retryable(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=False, status_code=404, text='Not Found')
            result = _call()
        assert result.ok is False
        assert result.retryable is False
        assert result.http_status == 404

    def test_generic_request_exception_is_not_retryable(self):
        with patch(
            'app.services.webhook_dispatcher.requests.post',
            side_effect=requests.RequestException('malformed url'),
        ):
            result = _call()
        assert result.ok is False
        assert result.retryable is False


class TestNeverRaises:
    def test_does_not_raise_on_connection_error(self):
        with patch(
            'app.services.webhook_dispatcher.requests.post',
            side_effect=requests.ConnectionError('offline'),
        ):
            # Must not raise -- caller має бути безпечним від збоїв.
            _call()

    def test_does_not_raise_on_5xx(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=False, status_code=503, text='x')
            _call()
