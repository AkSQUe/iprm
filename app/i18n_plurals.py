"""Локалізована плюралізація фіксованого набору іменників (бали, місця тощо).

gettext погано підходить, коли мова-джерела (укр) має 3 плюральні форми:
знадобився б окремий uk-каталог. Тут форми зберігаються централізовано
per-locale, а правило вибору -- слов'янське (3 форми: one/few/many) для
uk/ru і просте (2 форми) для en.

Використання в шаблоні: {{ n | plural('bpr_points') }} -> лише форма
іменника для поточної локалі (число підставляється окремо, як і раніше).
Нові іменники додавати у PLURAL_FORMS.
"""
from app.i18n import DEFAULT_LANGUAGE

# Порядок форм: (one, few, many) для слов'янських; (one, other) для en.
PLURAL_FORMS = {
    'bpr_points': {
        'uk': ('бал БПР', 'бали БПР', 'балів БПР'),
        'ru': ('балл БПР', 'балла БПР', 'баллов БПР'),
        'en': ('BPR point', 'BPR points'),
    },
    'points': {
        'uk': ('бал', 'бали', 'балів'),
        'ru': ('балл', 'балла', 'баллов'),
        'en': ('point', 'points'),
    },
    'bonus_points': {
        'uk': ('бонусний бал', 'бонусні бали', 'бонусних балів'),
        'ru': ('бонусный балл', 'бонусных балла', 'бонусных баллов'),
        'en': ('bonus point', 'bonus points'),
    },
    'topic_blocks': {
        'uk': ('тематичний блок', 'тематичні блоки', 'тематичних блоків'),
        'ru': ('тематический блок', 'тематических блока', 'тематических блоков'),
        'en': ('topic module', 'topic modules'),
    },
    'free_seats': {
        'uk': ('вільне місце', 'вільні місця', 'вільних місць'),
        'ru': ('свободное место', 'свободных места', 'свободных мест'),
        'en': ('seat available', 'seats available'),
    },
    'seats': {
        'uk': ('місце', 'місця', 'місць'),
        'ru': ('место', 'места', 'мест'),
        'en': ('seat', 'seats'),
    },
    'years': {
        'uk': ('рік', 'роки', 'років'),
        'ru': ('год', 'года', 'лет'),
        'en': ('year', 'years'),
    },
}


def _slavic_index(n):
    """0=one (1, 21...), 1=few (2-4, 22-24...), 2=many (0, 5-20, 11-14...)."""
    mod10, mod100 = n % 10, n % 100
    if mod10 == 1 and mod100 != 11:
        return 0
    if 2 <= mod10 <= 4 and not 10 <= mod100 < 20:
        return 1
    return 2


def _active_language():
    try:
        from flask_babel import get_locale
        return str(get_locale() or DEFAULT_LANGUAGE)
    except Exception:
        return DEFAULT_LANGUAGE


def plural(n, key, lang=None):
    """Форма іменника key для кількості n у поточній (або заданій) локалі."""
    lang = lang or _active_language()
    forms_by_lang = PLURAL_FORMS.get(key)
    if not forms_by_lang:
        return key
    forms = forms_by_lang.get(lang) or forms_by_lang[DEFAULT_LANGUAGE]
    try:
        n = abs(int(n))
    except (TypeError, ValueError):
        return forms[-1]
    if len(forms) == 2:  # 2-формні мови (en): one / other
        return forms[0] if n == 1 else forms[1]
    return forms[_slavic_index(n)]
