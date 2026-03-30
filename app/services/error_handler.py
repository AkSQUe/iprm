"""Централізований обробник помилок з логуванням в БД."""
import hashlib
import threading
from datetime import datetime, timedelta, timezone

from flask import request, current_app
from flask_login import current_user
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import DBAPIError, PendingRollbackError

from app.extensions import db
from app.models.error_log import ErrorLog


# Сегменти URL, характерні для сканерів
_SCANNER_SEGMENTS = frozenset({
    'wp-admin', 'wp-login', 'wp-content', 'wp-includes', 'wp-json',
    'wordpress', 'xmlrpc', 'phpmyadmin', 'adminer', 'cgi-bin',
    'geoserver', 'solr', 'jenkins', 'actuator', 'manager',
    'telescope', 'vendor', 'node_modules', 'graphql', 'swagger',
})

# HTTP-методи сканерів
_SCANNER_METHODS = frozenset({
    'PROPFIND', 'PROPPATCH', 'MKCOL', 'COPY', 'MOVE',
    'LOCK', 'UNLOCK', 'TRACE', 'TRACK', 'CONNECT', 'SEARCH',
})

# Rate limiting
_error_cache = {}
_cache_lock = threading.RLock()
_cache_cleanup_at = datetime.now(timezone.utc)
_COOLDOWN = 60
_MAX_CACHE = 10000


def _is_junk_request(status_code, url):
    """Перевіряє чи запит від сканера/бота."""
    if not url:
        return False
    path = url.split('?', 1)[0].rstrip('/')
    segments = path.strip('/').split('/')

    if not segments or not segments[-1]:
        return False

    last = segments[-1]

    if status_code == 404:
        if '.' in last:
            return True
        if len(last) <= 2:
            return True
        if '..' in path:
            return True

    lower_segments = {s.lower() for s in segments}
    if lower_segments & _SCANNER_SEGMENTS:
        return True

    if status_code == 405:
        try:
            if request.method in _SCANNER_METHODS:
                return True
        except RuntimeError:
            pass

    return False


def _should_log(status_code, url, message):
    """Rate limiting: не логувати дублікати протягом 60с."""
    global _cache_cleanup_at

    if _is_junk_request(status_code, url):
        return False

    sig = hashlib.sha256(f'{status_code}:{url}:{message}'.encode()).hexdigest()

    with _cache_lock:
        now = datetime.now(timezone.utc)
        if (now - _cache_cleanup_at).total_seconds() > 300:
            cutoff = now - timedelta(seconds=_COOLDOWN * 2)
            _error_cache.clear()
            _cache_cleanup_at = now

        if sig in _error_cache:
            if (now - _error_cache[sig]).total_seconds() < _COOLDOWN:
                return False

        if len(_error_cache) >= _MAX_CACHE:
            _error_cache.clear()
        _error_cache[sig] = now
        return True


def _log_to_db(error, status_code, message):
    """Записати помилку в БД з rate limiting."""
    try:
        if isinstance(error, (DBAPIError, PendingRollbackError)):
            try:
                db.session.rollback()
            except Exception:
                return None

        url = request.url if request else 'unknown'
        if not _should_log(status_code, url, message):
            return None

        user = current_user if current_user.is_authenticated else None
        return ErrorLog.log_error(
            exception=error,
            request=request,
            user=user,
            error_code=status_code,
            error_message=message,
        )
    except Exception as e:
        current_app.logger.error(f'DB error logging failed: {e}')
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def init_error_handlers(app):
    """Ініціалізувати обробники помилок для Flask app."""

    for code in (400, 401, 403, 404, 405, 429, 500, 503):
        app.register_error_handler(
            code,
            lambda error, c=code: _handle_error(error, c),
        )

    @app.errorhandler(Exception)
    def handle_unhandled(error):
        if isinstance(error, (DBAPIError, PendingRollbackError)):
            try:
                db.session.rollback()
            except Exception:
                pass

        if isinstance(error, HTTPException):
            return _handle_error(error, error.code)
        current_app.logger.exception(f'Unhandled: {request.method} {request.url}: {error}')
        return _handle_error(error, 500)


def _handle_error(error, status_code):
    """Обробити помилку: записати в БД та повернути відповідь."""
    from flask import render_template

    message = getattr(error, 'description', str(error))

    if status_code >= 500:
        current_app.logger.error(f'{status_code} {request.url}: {message}')

    _log_to_db(error, status_code, message)

    template_map = {
        401: 'errors/401.html',
        403: 'errors/403.html',
        404: 'errors/404.html',
        500: 'errors/500.html',
    }
    template = template_map.get(status_code, 'errors/500.html')

    try:
        return render_template(template, active_nav=None), status_code
    except Exception:
        return f'Error {status_code}', status_code
