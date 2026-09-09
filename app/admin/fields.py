"""Кастомні WTForms-поля адмінки."""
from wtforms import DecimalField
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
