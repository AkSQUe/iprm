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


def posthog_keys_error(api_key, secondary_key, env_key=''):
    """Помилка в самих ключах або None.

    Спільне для форми в адмінці та імпорту .env: імпорт спершу обходив ці
    правила, і Personal API Key ('phx_...'), що дає читання даних проєкту,
    потрапив би в HTML кожної сторінки. Правила про прапорці сюди свідомо не
    входять -- експорт з прода несе прапорці, успадковані з env, і такий
    файл має імпортуватись.
    """
    from app.models.site_settings import SiteSettings

    if not SiteSettings.is_valid_posthog_key(api_key):
        return ('Project API Key починається з "phc_". Ключ, що починається '
                'з "phx_", -- це Personal API Key: він дає доступ до читання '
                'даних проєкту, і в HTML йому не місце.')
    if not SiteSettings.is_valid_posthog_key(secondary_key):
        return ('Додатковий Project API Key теж має починатися з "phc_". '
                'Personal API Key ("phx_") в HTML не місце.')
    # Той самий ключ двічі -- кожна подія рахувалась би в проєкті вдвічі.
    # Порівнюємо з ключем, який реально діятиме, включно з env.
    if secondary_key and secondary_key == (api_key or env_key):
        return ('Додатковий ключ збігається з основним. Вкажіть ключ іншого '
                'проєкту або залиште поле порожнім.')
    return None


def posthog_settings_error(*, api_key, secondary_key, enabled, recording,
                           secondary_recording, env_key=''):
    """Помилка у формі налаштувань PostHog або None."""
    error = posthog_keys_error(api_key, secondary_key, env_key)
    if error:
        return error
    # Увімкнути без ключа неможливо: інакше вийшла б збережена пустушка --
    # бейдж "Активно" при нулі зібраних даних.
    if enabled and not (api_key or env_key):
        return 'Щоб увімкнути PostHog, спершу вкажіть Project API Key.'
    # Запис сесій без самої аналітики не має сенсу -- SDK просто не
    # ініціалізується. Мовчки лишити галку увімкненою означало б показувати
    # в адмінці стан, якого насправді немає.
    if recording and not enabled:
        return 'Запис сесій працює лише разом з увімкненим PostHog.'
    if secondary_recording and not secondary_key:
        return 'Запис сесій у додатковий проєкт потребує його ключа.'
    return None


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
        # Додатковий проєкт: ті самі події, окремий екземпляр SDK. '' -- немає.
        'secondary_api_key': settings.effective_posthog_secondary_api_key,
        'secondary_session_recording':
            settings.effective_posthog_secondary_session_recording,
        # Розділ сайту як властивість кожної події. Дешевша заміна вимиканню
        # трекінгу в адмінці: дані збираються скрізь, а відфільтрувати
        # внутрішній трафік можна в UI PostHog, не чіпаючи код.
        'section': blueprint or 'public',
        'mask_all_text': is_admin_area,
    }
