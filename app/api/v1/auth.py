"""API key authentication for partner endpoints."""
import hmac
import logging
from functools import wraps

from flask import current_app, jsonify, request

from app.models.site_settings import SiteSettings

logger = logging.getLogger(__name__)


def _client_ip():
    """Best-effort client IP (враховує X-Forwarded-For за proxy)."""
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def require_api_key(fn):
    """Require X-API-Key header matching SiteSettings.partner_api_key.

    Uses constant-time comparison to avoid timing attacks.
    Returns 404 (not 401) when integration is disabled to avoid leaking existence.
    Failed authentication attempts логуються у app.logger (для детекції brute-force).
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        settings = SiteSettings.get()
        if not settings.partner_integration_enabled:
            return jsonify({'error': 'Not Found'}), 404

        expected = settings.partner_api_key
        if not expected:
            logger.warning(
                'api_auth: integration enabled but partner_api_key is empty '
                '(ip=%s path=%s)',
                _client_ip(), request.path,
            )
            return jsonify({'error': 'Integration misconfigured'}), 503

        provided = request.headers.get('X-API-Key', '')
        if not provided or not hmac.compare_digest(provided, expected):
            current_app.logger.warning(
                'api_auth: invalid key ip=%s path=%s has_header=%s',
                _client_ip(), request.path, bool(provided),
            )
            return jsonify({'error': 'Invalid API key'}), 401

        return fn(*args, **kwargs)

    return wrapper


def require_perf_key(fn):
    """Require X-API-Key header matching SiteSettings.perf_api_key.

    Окремий ключ від партнерського: приймання замірів швидкості -- інша зона
    довіри, і ротація одного не має ламати інше. Порожній ключ означає, що
    приймання вимкнено -> 404 (не 401), щоб не підтверджувати існування
    ендпоінта тому, хто його намацує.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = SiteSettings.get().perf_api_key
        if not expected:
            return jsonify({'error': 'Not Found'}), 404

        provided = request.headers.get('X-API-Key', '')
        if not provided or not hmac.compare_digest(provided, expected):
            current_app.logger.warning(
                'perf_auth: invalid key ip=%s path=%s has_header=%s',
                _client_ip(), request.path, bool(provided),
            )
            return jsonify({'error': 'Invalid API key'}), 401

        return fn(*args, **kwargs)

    return wrapper
