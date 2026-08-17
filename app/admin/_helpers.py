"""Спільні utilities для admin blueprint: коміт + form helpers +
валідатори і маскування для admin/integrations сторінок."""
import logging
import re
from datetime import datetime, timezone

from flask import current_app, flash
from sqlalchemy import func

from app.extensions import db

audit_logger = logging.getLogger('audit')

# === Regex-валідатори формату ідентифікаторів інтеграцій ===
# Apple Developer ID-и -- 10-символьні uppercase-alphanumeric.
_APPLE_ID_RE = re.compile(r'^[A-Z0-9]{10}$')
# Services ID -- reverse-DNS (com.example.web), допускаємо букви/цифри/крапки/дефіси.
_APPLE_SERVICES_ID_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]+\.[a-zA-Z0-9][a-zA-Z0-9._-]+$')
# Google OAuth Client ID завжди закінчується на .apps.googleusercontent.com.
_GOOGLE_CLIENT_ID_RE = re.compile(
    r'^[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com$'
)
# PEM-блок приватного ключа -- мінімальна перевірка: BEGIN/END маркери.
_PEM_BEGIN_RE = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')
_PEM_END_RE = re.compile(r'-----END [A-Z ]*PRIVATE KEY-----')


def is_valid_apple_id(value):
    """Apple Team ID або Key ID -- 10 uppercase-alphanumeric (або порожнє)."""
    if not value:
        return True
    return bool(_APPLE_ID_RE.match(value))


def is_valid_apple_services_id(value):
    """Services ID -- reverse-DNS-like рядок з крапками."""
    if not value:
        return True
    return bool(_APPLE_SERVICES_ID_RE.match(value))


def is_valid_apple_private_key(value):
    """PEM-блок з BEGIN/END PRIVATE KEY маркерами."""
    if not value:
        return True
    return bool(_PEM_BEGIN_RE.search(value) and _PEM_END_RE.search(value))


def is_valid_google_client_id(value):
    """Google OAuth client_id має формат N-XXX.apps.googleusercontent.com."""
    if not value:
        return True
    return bool(_GOOGLE_CLIENT_ID_RE.match(value))


# === Маскування секретів (один helper з різними стилями) ===

def mask_secret(value, style='tail'):
    """Замаскувати секрет для відображення в admin UI.

    style='tail'   -> '****' + last 4 chars   (короткі ключі: liqpay, recaptcha)
    style='edges'  -> first 4 + '****' + last 4 chars (Google client_secret)
    style='length' -> '**** (N chars)'        (PEM-блоки Apple)
    """
    if not value:
        return ''
    if style == 'length':
        return f'**** ({len(value)} chars)'
    if style == 'edges' and len(value) > 8:
        return value[:4] + '****' + value[-4:]
    # default tail
    if len(value) <= 4:
        return '****'
    return '****' + value[-4:]


# === Універсальний save-helper для admin integrations ===

def save_integration_settings(provider, settings, updates, audit_summary=None,
                               success_msg=None, error_msg=None):
    """Атомарно оновити SiteSettings + commit + audit + flash.

    provider     -- ключ-ідентифікатор інтеграції для audit-логу
                    (e.g. 'google_oauth', 'apple_signin', 'recaptcha').
    settings     -- SiteSettings instance (caller отримав через .get()).
    updates      -- dict {attr_name: value}; пишеться через setattr.
    audit_summary-- dict що записуємо в audit-лог як summary (наприклад
                    {'enabled': True, 'secret_set': True}). За замовч --
                    {k: bool(v) for k, v in updates.items()}.
    success_msg  -- flash для success (default 'Налаштування збережено').
    error_msg    -- flash для error  (default 'Помилка при збереженні').

    Повертає True при успіху, False при exception.
    """
    from flask_login import current_user

    for attr, value in updates.items():
        setattr(settings, attr, value)

    if audit_summary is None:
        audit_summary = {k: bool(v) for k, v in updates.items()}

    try:
        db.session.commit()
        audit_logger.info(
            'integration_updated provider=%s admin=%s changes=%s',
            provider,
            getattr(current_user, 'email', 'unknown'),
            audit_summary,
        )
        flash(success_msg or 'Налаштування збережено', 'success')
        return True
    except Exception:
        db.session.rollback()
        audit_logger.exception(
            'integration_save_failed provider=%s admin=%s',
            provider, getattr(current_user, 'email', 'unknown'),
        )
        flash(error_msg or 'Помилка при збереженні', 'error')
        return False


# === Rotation reminders для секретів інтеграцій ===

class RotationStatus:
    """Стан ротації секрета. Відображається у admin UI як кольоровий бейдж."""
    UNKNOWN = 'unknown'        # set_at NULL -- секрет з legacy-епохи
    FRESH = 'fresh'            # < soft_threshold -- зелений
    AGING = 'aging'            # >= soft, < hard -- янтарний
    STALE = 'stale'            # >= hard -- червоний
    EMPTY = 'empty'            # секрет не встановлено зовсім


# Per-provider пороги (м'який / жорсткий) у днях. М'який -- "розгляньте
# ротацію"; жорсткий -- "наполегливо рекомендуємо".
ROTATION_THRESHOLDS = {
    'liqpay_private_key':            (180, 365),
    'google_oauth_client_secret':    (180, 365),
    'apple_private_key':             (90, 180),    # агресивніше -- Apple ключ може бути revoked
    'recaptcha_secret_key':          (365, 730),   # reCAPTCHA рідко ротується
}


def rotation_status(set_at, threshold_key=None,
                    soft_days=None, hard_days=None,
                    is_secret_present=True):
    """Обчислити статус ротації за `set_at` (datetime with tz) і порогами.

    threshold_key -- ключ з ROTATION_THRESHOLDS (зручний спосіб задати
        порогів через стандартні значення).
    Або задайте soft_days/hard_days напряму.
    is_secret_present -- чи є взагалі секрет (False => EMPTY незалежно від set_at).

    Повертає dict:
      status      -- 'unknown' | 'fresh' | 'aging' | 'stale' | 'empty'
      age_days    -- кількість днів від встановлення (None якщо unknown/empty)
      label       -- людино-читний текст для UI ("3 місяці тому")
      badge_class -- CSS-клас для бейджа
      next_rotation_days -- через скільки днів треба ротувати (None якщо stale)
    """
    if not is_secret_present:
        return {
            'status': RotationStatus.EMPTY,
            'age_days': None,
            'label': 'Секрет не встановлено',
            'badge_class': 'badge--draft',
            'next_rotation_days': None,
        }

    if set_at is None:
        return {
            'status': RotationStatus.UNKNOWN,
            'age_days': None,
            'label': 'Дата встановлення невідома',
            'badge_class': 'badge--pending',
            'next_rotation_days': None,
        }

    if threshold_key is not None:
        soft_days, hard_days = ROTATION_THRESHOLDS[threshold_key]
    if soft_days is None or hard_days is None:
        raise ValueError('rotation_status: pass threshold_key OR soft/hard_days')

    now = datetime.now(timezone.utc)
    delta = now - set_at
    age_days = int(delta.total_seconds() // 86400)

    if age_days < soft_days:
        status = RotationStatus.FRESH
        badge_class = 'badge--active'
    elif age_days < hard_days:
        status = RotationStatus.AGING
        badge_class = 'badge--published'
    else:
        status = RotationStatus.STALE
        badge_class = 'badge--draft'

    return {
        'status': status,
        'age_days': age_days,
        'label': _humanize_age(age_days),
        'badge_class': badge_class,
        'next_rotation_days': max(0, hard_days - age_days),
    }


def _humanize_age(age_days):
    """Перетворити дні у короткий людино-читний текст."""
    if age_days < 1:
        return 'менше дня тому'
    if age_days < 7:
        return f'{age_days} {_plural(age_days, "день", "дні", "днів")} тому'
    if age_days < 60:
        weeks = age_days // 7
        return f'{weeks} {_plural(weeks, "тиждень", "тижні", "тижнів")} тому'
    if age_days < 365:
        months = age_days // 30
        return f'{months} {_plural(months, "місяць", "місяці", "місяців")} тому'
    years = age_days // 365
    return f'{years} {_plural(years, "рік", "роки", "років")} тому'


def _plural(n, one, few, many):
    """Українські форми числівників (1 день / 2 дні / 5 днів)."""
    n_abs = abs(n) % 100
    n_mod = n_abs % 10
    if 10 < n_abs < 20:
        return many
    if n_mod == 1:
        return one
    if 2 <= n_mod <= 4:
        return few
    return many


# === Phase A: validate-before-save для секретів ===
# Перш ніж записати новий секрет у БД -- робимо live API-перевірку.
# Якщо невірний -- відмова, інтеграція не ламається.

def validate_recaptcha_secret(secret_key, timeout=5):
    """Перевірити secret_key через siteverify з bogus-токеном.

    Повертає (ok: bool, message: str). ok=True означає що секрет
    приймається Google'ом.
    """
    if not secret_key:
        return False, 'Secret key порожній'
    import json
    from urllib.parse import urlencode
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    body = urlencode({
        'secret': secret_key,
        'response': '___validation___',
    }).encode()
    try:
        req = Request(
            'https://www.google.com/recaptcha/api/siteverify',
            data=body, method='POST',
        )
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (URLError, TimeoutError) as e:
        return False, f'Не вдалося з\'єднатися з siteverify: {e}'
    except (json.JSONDecodeError, ValueError) as e:
        return False, f'Некоректна відповідь Google: {e}'

    codes = data.get('error-codes', []) or []
    if 'invalid-input-secret' in codes:
        return False, 'Google: secret key невалідний за форматом'
    if 'invalid-input-response' in codes or 'timeout-or-duplicate' in codes:
        # bogus-токен очікувано відхилено -- значить мережа+secret OK.
        return True, 'siteverify приймає secret (bogus-токен відхилено)'
    return False, f'Несподівана відповідь: codes={",".join(codes) or "немає"}'


def validate_apple_credentials(team_id, services_id, key_id, private_key_pem):
    """Перевірити Apple credentials через JWT-signing з новими ключами.

    Якщо JWT успішно підписався -- усі 4 параметри валідні. Помилка
    зазвичай означає що private_key битий або не у форматі PEM.
    """
    if not (team_id and services_id and key_id and private_key_pem):
        return False, 'Не всі параметри передано'
    try:
        from app.services.apple_signin import _generate_client_secret
        token = _generate_client_secret(team_id, services_id, key_id, private_key_pem)
        if not token or len(token) < 50:
            return False, 'JWT не зміг бути згенерованим'
        return True, 'client_secret JWT успішно підписано'
    except Exception as e:
        return False, f'Помилка JWT-signing: {str(e)[:200]}'


def validate_liqpay_credentials(public_key, private_key, sandbox, timeout=5):
    """Викликати LiqPay check_status з НОВИМИ ключами. Якщо API повернув
    err_code=payment_not_found -- ключі валідні (підпис прийнятий)."""
    if not (public_key and private_key):
        return False, 'Обидва ключі обов\'язкові'
    try:
        from app.services.liqpay import LiqPayService
        service = LiqPayService(
            public_key=public_key, private_key=private_key, sandbox=sandbox,
        )
        result = service.check_status('VALIDATION-TEST', timeout=timeout)
    except TypeError:
        # Старий LiqPayService.check_status без timeout-параметра.
        try:
            result = service.check_status('VALIDATION-TEST')
        except Exception as e:
            return False, f'Помилка виклику: {str(e)[:200]}'
    except Exception as e:
        return False, f'Помилка виклику: {str(e)[:200]}'

    if result is None:
        return False, 'Немає відповіді від LiqPay API (мережа/таймаут)'
    err = result.get('err_code', '')
    if err == 'payment_not_found':
        return True, 'Ключі валідні (API responsive)'
    if err in ('signature', 'invalid_signature'):
        return False, 'LiqPay відхилив підпис – private_key невірний'
    desc = result.get('err_description', '')
    return False, f'Несподівана відповідь LiqPay: err_code={err!r} {desc}'


def try_commit(log_context='', error_msg='Помилка при збереженні'):
    """Виконати db.session.commit() з уніфікованою обробкою помилок.

    Повертає True при успіху. При помилці: rollback, логує через
    current_app.logger.exception, flash-ить error_msg і повертає False.
    """
    try:
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        current_app.logger.exception('DB commit failed: %s', log_context)
        flash(error_msg, 'error')
        return False


def populate_trainer_choices(form, empty_label='– Default-тренер не обрано –'):
    """Заповнити form.trainer_id.choices активними тренерами."""
    from app.models.trainer import Trainer
    trainers = (
        Trainer.query.filter_by(is_active=True)
        .order_by(Trainer.full_name)
        .all()
    )
    form.trainer_id.choices = [(0, empty_label)] + [
        (t.id, t.full_name) for t in trainers
    ]


def course_request_counts(status='pending', course_ids=None):
    """Агреговане {course_id: count} для CourseRequest з заданим статусом.

    Один запит замість N+1 через Course.pending_requests_count property.
    """
    from app.models.course_request import CourseRequest
    q = db.session.query(
        CourseRequest.course_id,
        func.count(CourseRequest.id),
    ).filter(CourseRequest.status == status)
    if course_ids is not None:
        q = q.filter(CourseRequest.course_id.in_(course_ids))
    return dict(q.group_by(CourseRequest.course_id).all())
