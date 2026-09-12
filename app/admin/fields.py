"""Кастомні WTForms-поля адмінки."""
from wtforms import DecimalField, SelectMultipleField
from wtforms.validators import ValidationError
from wtforms.widgets import TextInput

from app.utils import format_points, parse_points


class PointsField(DecimalField):
    """Дробові бали БПР з комою або крапкою на вводі.

    Віджет саме текстовий: <input type="number"> у браузері не приймає кому,
    і поле «4,5» доходить до сервера порожнім ще до будь-якої валідації.
    """

    widget = TextInput()

    def __init__(self, *args, **kwargs):
        render_kw = dict(kwargs.pop('render_kw', None) or {})
        render_kw.setdefault('inputmode', 'decimal')
        super().__init__(*args, render_kw=render_kw, **kwargs)

    def process_formdata(self, valuelist):
        if not valuelist:
            return
        try:
            self.data = parse_points(valuelist[0])
        except ValueError:
            self.data = None
            raise ValueError(self.gettext('Введіть число, напр. 4,5'))

    def _value(self):
        if self.raw_data:
            return self.raw_data[0]
        return format_points(self.data)


class TrainerSelectField(SelectMultipleField):
    """Мультиселект тренерів з українським текстом відмови.

    Базовий SelectMultipleField на чужий id відповідає англійським
    "'X' is not a valid choice for this field" -- єдиним англійським рядком
    серед української форми. А трапляється ця відмова не лише при підміні
    поля: id деактивованого тренера, якого прибрали зі складу й тут-таки
    спробували повернути, теж не входить у choices (див.
    populate_trainer_choices), і менеджер має прочитати, ЩО саме сталося.
    """

    def pre_validate(self, form):
        allowed = {value for value, _label in self.iter_choices_tuples()}
        for value in self.data or []:
            if value not in allowed:
                raise ValidationError(
                    'Такого тренера немає серед доступних: він міг стати '
                    'неактивним, поки форма була відкрита. Оновіть сторінку.'
                )

    def iter_choices_tuples(self):
        """(value, label) для choices у будь-якому з підтримуваних форматів.

        `choices` тут завжди список пар (див. populate_trainer_choices), але
        WTForms дозволяє і плаский список значень -- звід до пар лишає
        pre_validate робочим, якщо колись передадуть саме такий.
        """
        for choice in self.choices or []:
            if isinstance(choice, (list, tuple)):
                yield choice[0], choice[1]
            else:
                yield choice, choice
