"""Tests for app.services.token_service -- email confirmation tokens."""
import time
import pytest
from app.services.token_service import generate_confirmation_token, confirm_token


class TestGenerateToken:
    def test_generates_string(self, app):
        token = generate_confirmation_token(42)
        assert isinstance(token, str)
        assert len(token) > 10

    def test_different_users_different_tokens(self, app):
        t1 = generate_confirmation_token(1)
        t2 = generate_confirmation_token(2)
        assert t1 != t2


class TestConfirmToken:
    def test_valid_token_returns_user_id(self, app):
        token = generate_confirmation_token(99)
        result = confirm_token(token)
        assert result == 99

    def test_expired_token_returns_none(self, app):
        token = generate_confirmation_token(99)
        time.sleep(1)
        result = confirm_token(token, max_age=0)
        assert result is None

    def test_invalid_token_returns_none(self, app):
        result = confirm_token('definitely-not-a-valid-token')
        assert result is None

    def test_tampered_token_returns_none(self, app):
        token = generate_confirmation_token(99)
        tampered = token[:-4] + 'XXXX'
        result = confirm_token(tampered)
        assert result is None
