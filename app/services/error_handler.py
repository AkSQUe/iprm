"""Централізований обробник помилок з логуванням в БД."""
import hashlib
import re
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import request, current_app
from flask_login import current_user
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import DBAPIError, PendingRollbackError

from app.extensions import db
from app.models.error_log import ErrorLog


# Сегменти URL, характерні для сканерів вразливостей
_SCANNER_SEGMENTS = frozenset({
    'wp-admin', 'wp-login', 'wp-content', 'wp-includes', 'wp-json',
    'wordpress', 'xmlrpc', 'phpmyadmin', 'adminer', 'cgi-bin',
    'geoserver', 'solr', 'jenkins', 'actuator', 'manager',
    'telescope', 'vendor', 'node_modules', 'graphql', 'swagger',
    # Часті цілі автосканерів (з реальних логів):
    'phpinfo', '_profiler', 'containers', 'sdk', 'weblanguage',
    'backup', 'credentials', 'eval-stdin', 'phpunit', 'thinkphp',
    'struts', 'owa', 'autodiscover', 'boaform', 'console', 'server-status',
    'weblanguage', 'systembc', 'login.action', 'hudson', 'dns-query',
})

# Ін'єкції у query/шляху (RCE/LFI спроби) -- завжди сканер
_SCANNER_INJECTION_RE = re.compile(
    r'php://|auto_prepend_file|allow_url_include|/etc/passwd|'
    r'base64_decode|call_user_func|\$\{|%ad|\.\./',
    re.IGNORECASE,
)

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
    """Перевіряє чи запит від сканера/бота (RCE/LFI спроби, дотфайли,
    відомі сканерські сегменти, сканерські HTTP-методи)."""
    if not url:
        return False

    if _SCANNER_INJECTION_RE.search(url):
        return True

    path = url.split('?', 1)[0].rstrip('/')
    segments = [s for s in path.strip('/').split('/') if s]
    if not segments:
        return False

    # Дотфайли/дотдиректорії: .git, .env, .aws, .ssh, .svn, .well-known тощо.
    if any(s.startswith('.') for s in segments):
        return True

    lower_segments = {s.lower() for s in segments}
    if lower_segments & _SCANNER_SEGMENTS:
        return True

    last = segments[-1]
    if status_code == 404:
        if '.' in last:       # x.php, config.json, *.bak ...
            return True
        if len(last) <= 2:
            return True
        if '..' in path:
            return True

    if status_code == 405:
        try:
            if request.method in _SCANNER_METHODS:
                return True
        except RuntimeError:
            pass

    return False


def _is_internal_referrer():
    """Чи прийшов запит за внутрішнім посиланням (referrer з нашого домену).
    Для 404/405 це ознака реально зламаного посилання, а не бота."""
    try:
        ref = request.referrer
        if not ref:
            return False
        return urlparse(ref).netloc.split(':')[0] == request.host.split(':')[0]
    except Exception:
        return False


def _should_log(status_code, url, message):
    """Чи писати помилку в БД. Відсіюємо ботів/сканерів і дублікати (60с)."""
    global _cache_cleanup_at

    if _is_junk_request(status_code, url):
        return False

    # 404/405 -- майже завжди автосканери. Логуємо лише коли це зламане
    # ВНУТРІШНЄ посилання (referrer з нашого домену), інакше -- ігноруємо.
    if status_code in (404, 405) and not _is_internal_referrer():
        return False

    sig = hashlib.sha256(f'{status_code}:{url}:{message}'.encode()).hexdigest()

    with _cache_lock:
        now = datetime.now(timezone.utc)
        if (now - _cache_cleanup_at).total_seconds() > 300:
            cutoff = now - timedelta(seconds=_COOLDOWN * 2)
            for k in [k for k, v in _error_cache.items() if v < cutoff]:
                del _error_cache[k]
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

        try:
            url = request.url
        except RuntimeError:
            url = 'unknown'
        if not _should_log(status_code, url, message):
            return None

        try:
            user = current_user if current_user.is_authenticated else None
        except Exception:
            user = None
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
