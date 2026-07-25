"""Спільні хелпери auth-блупринта.

Окремий модуль, щоб routes.py і oauth.py користувались однією реалізацією
без циклічного імпорту (обидва імпортують звідси, звідси -- нічого з app).
"""
from urllib.parse import urlparse


def is_safe_redirect_url(target):
    """Чи безпечно редіректити на target після входу.

    Дозволяємо ЛИШЕ відносні шляхи в межах сайту: без схеми, без хоста
    і без "//" на початку (протокол-відносний URL веде на чужий домен).
    """
    if not target:
        return False
    parsed = urlparse(target)
    return (not parsed.netloc and not parsed.scheme
            and target.startswith('/') and not target.startswith('//'))
