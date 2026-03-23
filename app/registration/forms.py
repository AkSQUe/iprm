from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField
from wtforms.validators import DataRequired, Length, Optional, NumberRange


class EventRegistrationForm(FlaskForm):
    phone = StringField(
        'Телефон',
        validators=[DataRequired(message='Телефон обов\'язковий'), Length(max=20)],
        render_kw={'placeholder': '+380XXXXXXXXX', 'autocomplete': 'tel'},
    )
    specialty = StringField(
        'Спеціальність',
        validators=[DataRequired(message='Спеціальність обов\'язкова'), Length(max=200)],
        render_kw={'placeholder': 'Наприклад: стоматолог, ортопед'},
    )
    workplace = StringField(
        'Місце роботи',
        validators=[DataRequired(message='Місце роботи обов\'язкове'), Length(max=300)],
        render_kw={'placeholder': 'Назва клініки або закладу'},
    )
    experience_years = IntegerField(
        'Стаж роботи (років)',
        validators=[Optional(), NumberRange(min=0, max=70)],
        render_kw={'placeholder': '0'},
    )
    license_number = StringField(
        'Номер ліцензії',
        validators=[Optional(), Length(max=50)],
        render_kw={'placeholder': 'Номер ліцензії лікаря'},
    )
