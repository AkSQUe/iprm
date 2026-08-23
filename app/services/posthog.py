"""PostHog -- рішення про активність трекінгу на поточній сторінці.

Той самий мотив, що і в services/meta_pixel.py: активність питають ЩОНАЙМЕНШЕ
двоє -- partial (чи вставляти скрипт) і CSP-хук (чи дозволяти blob-воркер та
домени кабінету). Тримати умову в обох означало б, що вони рано чи пізно
розійдуться, і найгірший варіант тут тихий: CSP світить дірку там, де скрипта
вже немає. Тому рішення живе в одному місці.

Вибір джерела ключа (БД чи env) лишається у властивостях SiteSettings -- це
налаштування. Тут поверх нього накладається те, що залежить від ЗАПИТУ:
розділ сайту і глибина маскування реплею.

На відміну від Meta Pixel, блупринтів-винятків тут НЕМАЄ: власник свідомо
обрав трекінг скрізь, включно з адмінкою. Замість вимикання адмінка
позначається властивістю ``iprm_section`` (щоб її можна було відфільтрувати
в самому PostHog) і отримує максимальне маскування реплею.
"""

# Блупринти, де запис сесії маскує ВЕСЬ текст, а не лише поля вводу.
#
# Адмінка -- це списки учасників з ПІБ, телефонами і медпрофілями. Реплей із
# самим лише maskAllInputs зняв би їх на відео: маскування полів ховає те, що
# ВВОДЯТЬ, а не те, що вже ВІДРЕНДЕРЕНО на сторінці. Тут лишаються кліки,
# скрол і навігація -- тобто те, заради чого реплей в адмінці й вмикали.
FULL_TEXT_MASK_BLUEPRINTS = frozenset({'admin'})


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

    return {
        'project_api_key': key,
        'api_host': current_app.config.get('POSTHOG_API_HOST', '/ngx-e'),
        'ui_host': current_app.config.get(
            'POSTHOG_UI_HOST', 'https://eu.posthog.com'),
        'session_recording': settings.effective_posthog_session_recording,
        # Розділ сайту як властивість кожної події. Дешевша заміна вимиканню
        # трекінгу в адмінці: дані збираються скрізь, а відфільтрувати
        # внутрішній трафік можна в UI PostHog, не чіпаючи код.
        'section': blueprint or 'public',
        'mask_all_text': blueprint in FULL_TEXT_MASK_BLUEPRINTS,
    }
