"""Тести кастомного WTForms-поля дробових балів БПР.

`PointsField` не можна прив'язати через `UnboundField.bind` з голою формою
(WTForms вимагає `form.meta`), тому тут використовується справжня
`FlaskForm`-нащадок замість `_Form` з брифу.
"""
from decimal import Decimal

from flask_wtf import FlaskForm
from werkzeug.datastructures import MultiDict
from wtforms.validators import Optional

from app.admin.fields import PointsField


class _F(FlaskForm):
    class Meta:
        csrf = False

    cpd = PointsField('Бали', validators=[Optional()])


def test_points_field_parses_comma(app):
    with app.test_request_context('/'):
        form = _F(formdata=MultiDict({'cpd': '4,5'}))
        assert form.cpd.data == Decimal('4.50')


def test_points_field_parses_dot(app):
    with app.test_request_context('/'):
        form = _F(formdata=MultiDict({'cpd': '4.5'}))
        assert form.cpd.data == Decimal('4.50')


def test_points_field_renders_without_trailing_zeros(app):
    with app.test_request_context('/'):
        form = _F(data={'cpd': Decimal('9.00')})
        assert form.cpd._value() == '9'

        form = _F(data={'cpd': Decimal('7.50')})
        assert form.cpd._value() == '7,5'


def test_points_field_renders_text_input(app):
    with app.test_request_context('/'):
        form = _F(data={'cpd': Decimal('7.50')})
        markup = str(form.cpd())
        assert 'type="text"' in markup
        assert 'inputmode="decimal"' in markup
