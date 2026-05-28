"""reCAPTCHA v3 verification.

- DB-first (SiteSettings), env-fallback (Flask config).
- Якщо інтеграція не enabled або не сконфігурована -- verify() повертає True
  (graceful: не блокуємо форми, поки адмін ще не налаштував).
- Усі результати логуються в audit-logger (для розбору false-positives).
"""
import json
import logging
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen, Request

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

VERIFY_URL = 'https://www.google.com/recaptcha/api/siteverify'


class RecaptchaService:

    def __init__(self, enabled, site_key, secret_key, score_threshold):
        self.enabled = bool(enabled)
        self.site_key = site_key or ''
        self.secret_key = secret_key or ''
        self.score_threshold = float(score_threshold or 0.5)

    @property
    def is_configured(self):
        """Готова до перевірки (увімкнено + є обидва ключі)."""
        return self.enabled and bool(self.site_key) and bool(self.secret_key)

    @property
    def is_active(self):
        """Public-side: чи треба вшивати JS у HTML (site_key є)."""
        return self.enabled and bool(self.site_key)

    def verify(self, token, expected_action=None, remote_ip=None, timeout=5):
        """Повертає (ok: bool, info: dict). Якщо не сконфігуровано -- (True, {'skipped': True}).

        info містить: score, action, error_codes -- для audit-logging.
        """
        if not self.is_configured:
            return True, {'skipped': True}

        if not token:
            audit_logger.info('reCAPTCHA: missing token (action=%s)', expected_action)
            return False, {'error': 'missing_token'}

        body = urlencode({
            'secret': self.secret_key,
            'response': token,
            'remoteip': remote_ip or '',
        }).encode('utf-8')

        try:
            req = Request(VERIFY_URL, data=body, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except (URLError, json.JSONDecodeError, TimeoutError) as e:
            logger.warning('reCAPTCHA verify network/parse error: %s', e)
            # Fail-open при недоступності Google API -- не блокуємо реальних
            # користувачів, але логуємо.
            audit_logger.warning(
                'reCAPTCHA: verify failed (network), allowing (action=%s)',
                expected_action,
            )
            return True, {'skipped': True, 'error': 'network'}

        success = bool(data.get('success'))
        score = float(data.get('score') or 0.0)
        action = data.get('action', '')
        error_codes = data.get('error-codes', []) or []

        info = {
            'success': success,
            'score': score,
            'action': action,
            'error_codes': error_codes,
            'threshold': self.score_threshold,
        }

        if not success:
            audit_logger.info(
                'reCAPTCHA: verify rejected by Google (action=%s, errors=%s)',
                expected_action, error_codes,
            )
            return False, info

        if expected_action and action and action != expected_action:
            audit_logger.info(
                'reCAPTCHA: action mismatch (expected=%s, got=%s)',
                expected_action, action,
            )
            return False, info

        if score < self.score_threshold:
            audit_logger.info(
                'reCAPTCHA: score below threshold (action=%s, score=%.2f, threshold=%.2f)',
                expected_action, score, self.score_threshold,
            )
            return False, info

        return True, info


def get_recaptcha_service(app=None):
    """SiteSettings -> Flask config fallback. Singleton-style фабрика."""
    from flask import current_app
    from app.models.site_settings import SiteSettings

    cfg = (app or current_app).config
    settings = SiteSettings.get()

    site_key = settings.recaptcha_site_key or cfg.get('RECAPTCHA_SITE_KEY', '')
    secret_key = settings.recaptcha_secret_key or cfg.get('RECAPTCHA_SECRET_KEY', '')
    # enabled і threshold: якщо в БД щось налаштовано -- беремо звідти,
    # інакше fallback env.
    if settings.recaptcha_site_key or settings.recaptcha_secret_key:
        enabled = settings.recaptcha_enabled
        threshold = settings.recaptcha_score_threshold
    else:
        enabled = cfg.get('RECAPTCHA_ENABLED', False)
        threshold = cfg.get('RECAPTCHA_SCORE_THRESHOLD', 0.5)

    return RecaptchaService(
        enabled=enabled,
        site_key=site_key,
        secret_key=secret_key,
        score_threshold=threshold,
    )


def verify_request(action, form=None):
    """Зручний helper для роутів. Бере token з form['g-recaptcha-response'].

    Повертає True, якщо сервіс не сконфігурований АБО токен валідний.
    Повертає False -- роут має відмовити (зазвичай flash + render).
    """
    from flask import request as flask_request

    service = get_recaptcha_service()
    if not service.is_configured:
        return True

    src = form or flask_request.form
    token = (src.get('g-recaptcha-response') or '').strip()
    remote_ip = (flask_request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
                 or flask_request.remote_addr)

    ok, _info = service.verify(token, expected_action=action, remote_ip=remote_ip)
    return ok
