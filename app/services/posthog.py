"""PostHog -- рішення про активність трекінгу на поточній сторінці.

Той самий мотив, що і в services/meta_pixel.py: активність питають
ЩОНАЙМЕНШЕ двоє -- partial (чи вставляти скрипт) і CSP-хук (чи дозволяти
blob-воркер та домени кабінету). Тримати умову в обох означало б, що вони
рано чи пізно розійдуться, і найгірший варіант тут тихий: CSP світить дірку
там, де скрипта вже немає. Тому рішення живе в одному місці.

Вибір джерела ключа і прапорців (БД чи env) лишається у властивостях
SiteSettings -- це налаштування. Тут поверх нього накладається те, що
залежить від ЗАПИТУ: розділ сайту, глибина маскування реплею і виняток
для адмінки.
"""

# Блупринти, які вважаються адмінкою.
#
# Для них два різні наслідки, і плутати їх не варто:
#   * effective_posthog_exclude_admin=True -- трекінгу тут немає взагалі;
#   * інакше трекінг є, але реплей маскує ВЕСЬ текст, а не лише поля вводу.
#
# Друге -- бо адмінка це списки учасників з ПІБ, телефонами і медпрофілями.
# maskAllInputs ховає те, що ВВОДЯТЬ, а не те, що вже відрендерено на
# сторінці; без maskTextSelector картки поїхали б у відеозапис.
ADMIN_BLUEPRINTS = frozenset({'admin'})

# Ендпоінт сторінки перевірки. Її суть у тому, щоб скрипт таки завантажився
# і надіслав подію, тож виняток "не трекати адмінку" на неї не поширюється --
# інакше перевіряти було б нічого. Знання про цей ендпоінт живе тут, а не в
# шаблоні: інакше умову довелося б повторювати ще й у CSP.
FORCED_ENDPOINTS = frozenset({'admin.posthog_test'})


def _normalize_api_host(value):
    """Прибрати кінцевий слеш, щоб не збирати '//static/array.js'.

    Шлях приходить з конфігу і його цілком реально записати як '/ngx-e/'.
    Подвійний слеш проксі не зламає, але дасть інший URL для кешу і
    неспівпадіння з локацією nginx у логах -- дешевше нормалізувати тут.
    """
    value = (value or '').strip()
    while value.endswith('/') and len(value) > 1:
        value = value[:-1]
    return value


def active_posthog_config(settings=None):
    """Конфіг PostHog для ПОТОЧНОГО запиту або None, якщо трекінгу тут немає.

    settings -- опційно вже завантажений SiteSettings, щоб не смикати сховище
    повторно, коли caller його вже має (CSP-хук).
    """
    from flask import current_app, g, has_request_context, request
    from app.models.site_settings import SiteSettings

    if settings is None:
        settings = getattr(g, 'site_settings', None)
        if settings is None:
            settings = SiteSettings.get()

    key = settings.effective_posthog_api_key
    if not key:
        return None

    blueprint = request.blueprint if has_request_context() else None
    endpoint = request.endpoint if has_request_context() else None
    is_admin_area = blueprint in ADMIN_BLUEPRINTS
    is_forced = endpoint in FORCED_ENDPOINTS

    if is_admin_area and not is_forced and settings.effective_posthog_exclude_admin:
        return None

    return {
        'project_api_key': key,
        'api_host': _normalize_api_host(
            current_app.config.get('POSTHOG_API_HOST', '/ngx-e')),
        'ui_host': current_app.config.get(
            'POSTHOG_UI_HOST', 'https://eu.posthog.com'),
        'session_recording': settings.effective_posthog_session_recording,
        # Розділ сайту як властивість кожної події. Дешевша заміна вимиканню
        # трекінгу в адмінці: дані збираються скрізь, а відфільтрувати
        # внутрішній трафік можна в UI PostHog, не чіпаючи код.
        'section': blueprint or 'public',
        'mask_all_text': is_admin_area,
    }
