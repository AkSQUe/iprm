"""Export/Import конфігурації admin/integrations як .env-блок.

Export: дамп публічних значень (client_id, services_id, GA, ...). Секрети
включаються опційно (admin тика чекбокс) -- для bootstrap'у staging/test
environments.

Import: parse paste'нутого .env-блоку через python-dotenv, compute diff
проти поточних SiteSettings (admin бачить що зміниться), apply (POST з
confirm-токеном для CSRF-захисту окремий step).

Mapping EXPORTABLE визначає які env-keys -> які SiteSettings-attributes,
з прапором is_secret для conditional-export.
"""
from datetime import datetime, timezone

# (env_key, settings_attr, is_secret, default_value).
# default_value -- нормалізатор для NULL у БД (legacy-рядки можуть мати
# NULL замість '' / False для не заданих колонок).
EXPORTABLE = [
    ('GOOGLE_OAUTH_ENABLED',       'google_oauth_enabled',       False, False),
    ('GOOGLE_OAUTH_CLIENT_ID',     'google_oauth_client_id',     False, ''),
    ('GOOGLE_OAUTH_CLIENT_SECRET', 'google_oauth_client_secret', True,  ''),

    ('APPLE_SIGNIN_ENABLED',       'apple_signin_enabled',       False, False),
    ('APPLE_TEAM_ID',              'apple_team_id',              False, ''),
    ('APPLE_SERVICES_ID',          'apple_services_id',          False, ''),
    ('APPLE_KEY_ID',               'apple_key_id',               False, ''),
    ('APPLE_PRIVATE_KEY',          'apple_private_key',          True,  ''),

    ('LIQPAY_PUBLIC_KEY',          'liqpay_public_key',          False, ''),
    ('LIQPAY_PRIVATE_KEY',         'liqpay_private_key',         True,  ''),
    ('LIQPAY_SANDBOX',             'liqpay_sandbox',             False, True),

    ('RECAPTCHA_ENABLED',          'recaptcha_enabled',          False, False),
    ('RECAPTCHA_SITE_KEY',         'recaptcha_site_key',         False, ''),
    ('RECAPTCHA_SECRET_KEY',       'recaptcha_secret_key',       True,  ''),
    ('RECAPTCHA_SCORE_THRESHOLD',  'recaptcha_score_threshold',  False, 0.5),

    ('GOOGLE_ANALYTICS_ID',        'google_analytics_id',        False, ''),
]


def _normalized_get(settings, attr, default):
    """getattr з нормалізацією None -> typed default."""
    try:
        value = getattr(settings, attr, default)
    except Exception:
        value = default
    if value is None:
        return default
    return value


def _format_value(value):
    """Серіалізувати Python-значення у env-string. Quote'ить значення з
    пробілами/спецсимволами; bool -> 'true'/'false'."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float):
        return repr(value)
    if value is None:
        return ''
    s = str(value)
    # PEM-блоки містять newlines -- escape їх щоб .env-формат не плутався.
    s = s.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '')
    needs_quote = any(c in s for c in (' ', '#', '"', "'"))
    if needs_quote:
        s = '"' + s.replace('"', '\\"') + '"'
    return s


def _parse_value(raw_value, current):
    """Конвертувати .env-string у тип таких самих як current. None values
    нормалізуємо до '' для strings, до current для bool/float (skip)."""
    if raw_value is None:
        raw_value = ''
    # Розгортаємо \\n назад у newlines (для PEM).
    raw_value = raw_value.replace('\\n', '\n')

    if isinstance(current, bool):
        return raw_value.strip().lower() in ('true', '1', 'yes', 'on')
    if isinstance(current, float):
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return current  # keep old if parse fails
    return raw_value


def export_env(settings, include_secrets):
    """Згенерувати .env-блок з SiteSettings.

    include_secrets=False -- лише публічні значення (безпечно
    репозитувати у git). True -- усе, для bootstrap'у нової інстанції.
    """
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    lines = [
        '# IPRM Integration Config Export',
        f'# Згенеровано: {now}',
        f'# include_secrets={"true" if include_secrets else "false"}',
    ]
    if include_secrets:
        lines.append('# УВАГА: цей файл містить секрети. Зберігайте у secret-store.')
    lines.append('')

    for env_key, attr, is_secret, default in EXPORTABLE:
        if is_secret and not include_secrets:
            lines.append(f'# {env_key}=<sec ret hidden>')
            continue
        value = _normalized_get(settings, attr, default)
        lines.append(f'{env_key}={_format_value(value)}')

    return '\n'.join(lines) + '\n'


def parse_env_text(text):
    """Parse .env-блок -> dict[env_key, raw_string_value].

    Використовуємо python-dotenv для коректного парсингу quoted values."""
    import io
    from dotenv import dotenv_values
    try:
        values = dotenv_values(stream=io.StringIO(text))
    except Exception:
        return {}
    # Залишаємо лише відомі ключі (whitelist по EXPORTABLE).
    allowed = {env_key for env_key, _, _, _ in EXPORTABLE}
    return {k: v for k, v in values.items() if k in allowed}


def compute_diff(parsed, settings):
    """Обчислити diff (parsed env vs SiteSettings). Повертає list of dicts:
    [{key, attr, is_secret, before, after, changed}].

    None у БД нормалізуємо до typed default (з EXPORTABLE) щоб roundtrip
    'export -> parse -> diff' давав 'без змін'.
    """
    diff = []
    for env_key, attr, is_secret, default in EXPORTABLE:
        if env_key not in parsed:
            continue
        current = _normalized_get(settings, attr, default)
        new_value = _parse_value(parsed[env_key], current)
        diff.append({
            'key': env_key,
            'attr': attr,
            'is_secret': is_secret,
            'before': current,
            'after': new_value,
            'changed': new_value != current,
        })
    return diff


def apply_parsed(parsed, settings):
    """Записати parsed значення у settings (не комітимо -- caller).
    Повертає кількість змін."""
    n = 0
    for env_key, attr, _, default in EXPORTABLE:
        if env_key not in parsed:
            continue
        current = _normalized_get(settings, attr, default)
        new_value = _parse_value(parsed[env_key], current)
        if new_value != current:
            setattr(settings, attr, new_value)
            n += 1
    return n
