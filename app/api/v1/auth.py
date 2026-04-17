"""API key authentication for partner endpoints."""
import hmac
from functools import wraps

from flask import jsonify, request

from app.models.site_settings import SiteSettings


def require_api_key(fn):
    """Require X-API-Key header matching SiteSettings.partner_api_key.

    Uses constant-time comparison to avoid timing attacks.
    Returns 404 (not 401) when integration is disabled to avoid leaking existence.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        settings = SiteSettings.get()
        if not settings.partner_integration_enabled:
            return jsonify({'error': 'Not Found'}), 404

        expected = settings.partner_api_key
        if not expected:
            return jsonify({'error': 'Integration misconfigured'}), 503

        provided = request.headers.get('X-API-Key', '')
        if not provided or not hmac.compare_digest(provided, expected):
            return jsonify({'error': 'Invalid API key'}), 401

        return fn(*args, **kwargs)

    return wrapper
