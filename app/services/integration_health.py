"""Live health-checks для admin/integrations area.

Кожен provider має власну check-функцію, що робить мінімально-інвазивний
запит до live-API (зазвичай discovery endpoint або відомо-невалідний
запит до verify-endpoint) і повертає dict з:

  status -- 'ok' | 'degraded' | 'down' | 'not_configured'
  detail -- людино-читний рядок з результатом (опційно)
  error  -- повідомлення про помилку (опційно, при down/degraded)
  checked_at -- datetime UTC коли востаннє перевірено

Кешуємо у пам'яті процесу на 60 секунд щоб уникнути hammering зовнішніх
API при rapid-refresh. ?refresh=1 на роуті очищає кеш.

Парелельний запуск через ThreadPoolExecutor: загальний час сторінки =
максимум по одному check'у (а не сума), бо checks незалежні.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from flask import current_app

logger = logging.getLogger(__name__)

# In-memory cache: {provider_key: (timestamp_unix, result_dict)}.
_CACHE = {}
_CACHE_TTL_SECONDS = 60
_HTTP_TIMEOUT_SECONDS = 5


# === Status enum (string-based, JSON-friendly) ===
class HealthStatus:
    OK = 'ok'
    DEGRADED = 'degraded'
    DOWN = 'down'
    NOT_CONFIGURED = 'not_configured'


# ----------------------------------------------------------------
# Окремі check-функції
# ----------------------------------------------------------------

def _check_google_oauth(settings):
    if not settings.is_google_oauth_configured:
        return {'status': HealthStatus.NOT_CONFIGURED}
    try:
        from app.services.google_oauth import GOOGLE_JWKS_URL
        r = requests.get(GOOGLE_JWKS_URL, timeout=_HTTP_TIMEOUT_SECONDS)
        r.raise_for_status()
        keys = r.json().get('keys', [])
        return {
            'status': HealthStatus.OK,
            'detail': f'JWKS endpoint доступний ({len(keys)} ключів)',
        }
    except requests.RequestException as e:
        return {'status': HealthStatus.DOWN, 'error': f'JWKS unreachable: {e}'}
    except Exception as e:
        return {'status': HealthStatus.DOWN, 'error': str(e)[:200]}


def _check_apple_signin(settings):
    if not settings.is_apple_signin_configured:
        return {'status': HealthStatus.NOT_CONFIGURED}
    try:
        from app.services.apple_signin import (
            APPLE_DISCOVERY_URL, _generate_client_secret,
        )
        r = requests.get(APPLE_DISCOVERY_URL, timeout=_HTTP_TIMEOUT_SECONDS)
        r.raise_for_status()
        # Перевіряємо що client_secret JWT генерується (validates private key).
        _generate_client_secret(
            settings.apple_team_id, settings.apple_services_id,
            settings.apple_key_id, settings.apple_private_key,
        )
        return {
            'status': HealthStatus.OK,
            'detail': 'Discovery OK, client_secret JWT підписується',
        }
    except requests.RequestException as e:
        return {'status': HealthStatus.DOWN, 'error': f'Discovery unreachable: {e}'}
    except Exception as e:
        # Зазвичай -- failure при підписі (приватний ключ битий).
        return {
            'status': HealthStatus.DEGRADED,
            'error': f'JWT-signing помилка: {str(e)[:200]}',
        }


def _check_liqpay(settings):
    from app.services.liqpay import get_liqpay_service
    service = get_liqpay_service(settings=settings)
    if not service.is_configured:
        return {'status': HealthStatus.NOT_CONFIGURED}
    try:
        # Запит про неіснуючий платіж -- очікуємо err_code=payment_not_found.
        # Це best-effort health-check без витрат на бік LiqPay.
        result = service.check_status('HEALTH-CHECK-NONEXISTENT')
        if result is None:
            return {'status': HealthStatus.DOWN, 'error': 'No response from LiqPay API'}
        err = result.get('err_code', '')
        status_val = result.get('status', '')
        if err == 'payment_not_found' or status_val:
            return {
                'status': HealthStatus.OK,
                'detail': 'API responsive (отримано payment_not_found)',
            }
        # invalid_signature або інша помилка -- ключі невірні.
        if err in ('signature', 'invalid_signature'):
            return {
                'status': HealthStatus.DOWN,
                'error': 'LiqPay reject-ить підпис (ключі невірні)',
            }
        return {
            'status': HealthStatus.DEGRADED,
            'detail': f'Несподівана відповідь: err_code={err!r}',
        }
    except Exception as e:
        return {'status': HealthStatus.DOWN, 'error': str(e)[:200]}


def _check_recaptcha(settings):
    from app.services.recaptcha import get_recaptcha_service
    service = get_recaptcha_service(settings=settings)
    if not service.secret_key:
        return {'status': HealthStatus.NOT_CONFIGURED}
    try:
        body = service._build_request_body('___healthcheck___')
        info = service._call_siteverify(body, timeout=_HTTP_TIMEOUT_SECONDS)
        if info.get('error') == 'network':
            return {'status': HealthStatus.DOWN, 'error': 'siteverify unreachable'}
        codes = info.get('error_codes', [])
        if 'invalid-input-secret' in codes:
            return {'status': HealthStatus.DOWN, 'error': 'Secret key невалідний'}
        # Очікуємо відмову з нашого bogus-токена -- значить мережа і secret OK.
        if 'invalid-input-response' in codes or 'timeout-or-duplicate' in codes:
            return {
                'status': HealthStatus.OK,
                'detail': 'siteverify responsive',
            }
        if not codes and info.get('success') is False:
            return {
                'status': HealthStatus.DOWN,
                'error': 'siteverify reject without code (secret bad?)',
            }
        return {
            'status': HealthStatus.DEGRADED,
            'detail': f'Неочікувані помилки: {",".join(codes)}',
        }
    except Exception as e:
        return {'status': HealthStatus.DOWN, 'error': str(e)[:200]}


def _check_google_analytics(settings):
    """GA -- fire-and-forget client-side; немає server-side ping. Перевіряємо
    лише формат активного ID."""
    from app.models.site_settings import SiteSettings
    eff = settings.effective_google_analytics_id
    if not eff:
        return {'status': HealthStatus.NOT_CONFIGURED}
    if SiteSettings.is_valid_ga_id(eff):
        return {
            'status': HealthStatus.OK,
            'detail': f'Measurement ID {eff} (server-side ping недоступний)',
        }
    return {
        'status': HealthStatus.DEGRADED,
        'error': f'Формат ID невалідний: {eff!r}',
    }


def _check_meta_pixel(settings):
    """Pixel -- client-side; server-side ping без access token неможливий
    (Graph API вимагає CAPI-токен, якого в цій інтеграції немає). Тому
    перевіряємо доступність CDN зі скриптом і формат активного ID."""
    from app.models.site_settings import SiteSettings
    eff = settings.effective_meta_pixel_id
    if not eff:
        if settings.meta_pixel_id:
            return {
                'status': HealthStatus.NOT_CONFIGURED,
                'detail': 'ID збережено, але трекінг вимкнено',
            }
        return {'status': HealthStatus.NOT_CONFIGURED}
    if not SiteSettings.is_valid_meta_pixel_id(eff):
        return {
            'status': HealthStatus.DEGRADED,
            'error': f'Формат ID невалідний: {eff!r}',
        }
    try:
        r = requests.head(
            'https://connect.facebook.net/en_US/fbevents.js',
            timeout=_HTTP_TIMEOUT_SECONDS, allow_redirects=True,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        # CDN недоступний з сервера -- у браузерів відвідувачів може бути
        # інакше, тож це degraded, а не down.
        return {
            'status': HealthStatus.DEGRADED,
            'error': f'fbevents.js недоступний з сервера: {e}',
        }
    return {
        'status': HealthStatus.OK,
        'detail': f'Pixel ID {eff}, fbevents.js доступний',
    }


# ----------------------------------------------------------------
# Реєстр + parallel runner
# ----------------------------------------------------------------

CHECKERS = {
    'liqpay': ('LiqPay', _check_liqpay),
    'google_oauth': ('Google OAuth', _check_google_oauth),
    'apple_signin': ('Apple Sign In', _check_apple_signin),
    'recaptcha': ('reCAPTCHA v3', _check_recaptcha),
    'google_analytics': ('Google Analytics 4', _check_google_analytics),
    'meta_pixel': ('Meta Pixel', _check_meta_pixel),
}


def _run_one(provider, settings):
    """Запустити одну check-функцію (без cache). Завжди повертає dict."""
    _, fn = CHECKERS[provider]
    try:
        result = fn(settings)
    except Exception as e:
        logger.exception('Health check raised for %s', provider)
        result = {'status': HealthStatus.DOWN, 'error': str(e)[:200]}
    result['checked_at'] = datetime.now(timezone.utc)
    return result


def _cached_run(provider, settings):
    """Запустити з cache (TTL 60s). При cache-hit повертає старий результат."""
    now = time.time()
    cached = _CACHE.get(provider)
    if cached and (now - cached[0] < _CACHE_TTL_SECONDS):
        return cached[1]
    result = _run_one(provider, settings)
    _CACHE[provider] = (now, result)
    return result


def clear_cache():
    """Викликається при ?refresh=1 на роуті."""
    _CACHE.clear()


def run_all_checks(settings, use_cache=True):
    """Запускає всі checks parallel у thread-pool. Повертає dict
    {provider_key: {'label': ..., 'status': ..., 'detail': ..., 'checked_at': ...}}.
    Загальний час -- максимум серед одиничних checks (~5s timeout).

    Thread-workers потребують app_context (бо service-factories звертаються
    до current_app.config за env-fallback'ами). Захоплюємо реальний app
    і push'аємо context всередині кожного потоку.
    """
    if not use_cache:
        clear_cache()

    runner = _cached_run if use_cache else _run_one
    app = current_app._get_current_object()

    def _worker(provider):
        with app.app_context():
            return runner(provider, settings)

    results = {}
    with ThreadPoolExecutor(max_workers=len(CHECKERS)) as ex:
        futures = {key: ex.submit(_worker, key) for key in CHECKERS}
        for key, (label, _) in CHECKERS.items():
            try:
                result = futures[key].result()
            except Exception as e:
                logger.exception('Health check thread crashed for %s', key)
                result = {
                    'status': HealthStatus.DOWN,
                    'error': str(e)[:200],
                    'checked_at': datetime.now(timezone.utc),
                }
            result['label'] = label
            result['key'] = key
            results[key] = result
    return results
