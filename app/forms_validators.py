"""Спільні WTForms-валідатори для форм адмінки й кабінету тренера.

Той самий підхід, що й `app/forms_medical.py` для полів медичної анкети:
одне джерело правди для валідатора, що інакше довелось би повторювати в
кожному модулі форм (`app/trainer_cabinet/forms.py`, `app/admin/forms.py`, ...).
"""
import re

from wtforms.validators import URL, ValidationError

from app.utils import HTTP_URL_PATTERN


class HttpUrl:
    """Посилання, яке потім стає href: лише http(s).

    URL() перевіряє лише синтаксис і пропускає `javascript://host/%0aalert(1)`
    (у href це виконуваний код). Схему перевіряємо першою і в тому ж
    валідаторі, щоб на `abc` не з'являлось дві однакові помилки поспіль.
    """

    def __init__(self, message):
        self.message = message
        self._url = URL(message=message)

    def __call__(self, form, field):
        if not re.match(HTTP_URL_PATTERN, field.data or '', re.IGNORECASE):
            raise ValidationError(self.message)
        self._url(form, field)
