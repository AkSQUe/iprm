"""Meta (Facebook) Pixel -- рішення про активність трекінгу на сторінці.

Активність вирішується щонайменше у трьох місцях: partial (чи вставляти
скрипт), base.html (чи підключати обробник подій) і CSP (чи дозволяти
домени Meta). Тримати умову в кожному з них означало б, що вони рано чи
пізно розійдуться -- найгірший варіант тут тихий: CSP дозволяє
facebook-домени на сторінках, де скрипта вже немає, тобто дірка без жодної
користі. Тому умова живе в одному місці.

Сам вибір джерела ID (БД чи env) лишається в
SiteSettings.effective_meta_pixel_id -- це властивість налаштувань. Тут
поверх нього накладається те, що залежить від запиту.
"""

# Блупринти, де Pixel не працює.
#
# admin: URL-и адмінки містять ідентифікатори клієнтів і потрапили б до Meta
# у складі кожної події; самі адміністратори дають сотні переглядів, які
# псують статистику конверсій і формують рекламні аудиторії з власного
# персоналу. Гейт за згодою тут не рятує -- localStorage спільний на домен,
# тож згода, дана на публічній сторінці, діяла б і в адмінці.
EXCLUDED_BLUEPRINTS = frozenset({'admin'})

# Єдиний виняток з правила вище: сторінка перевірки Pixel. Її суть у тому,
# щоб скрипт таки завантажився і надіслав подію -- інакше перевіряти нічого.
# Знання про цей ендпоінт живе тут, а не в шаблоні: інакше умову довелося б
# повторювати ще й у CSP.
FORCED_ENDPOINTS = frozenset({'admin.meta_pixel_test'})


def _is_forced():
    from flask import has_request_context, request
    return has_request_context() and request.endpoint in FORCED_ENDPOINTS


def active_pixel_id(settings=None):
    """ID Pixel для ПОТОЧНОГО запиту або '' якщо трекінгу тут немає.

    settings -- опційно вже завантажений SiteSettings, щоб не смикати
    сховище повторно, коли caller його вже має (CSP-хук).
    """
    from flask import g, has_request_context, request
    from app.models.site_settings import SiteSettings

    if settings is None:
        settings = getattr(g, 'site_settings', None)
        if settings is None:
            settings = SiteSettings.get()

    pixel_id = settings.effective_meta_pixel_id
    if not pixel_id:
        return ''
    if _is_forced():
        return pixel_id
    if has_request_context() and request.blueprint in EXCLUDED_BLUEPRINTS:
        return ''
    return pixel_id
