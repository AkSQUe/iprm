"""Спільні поля МОЗ-анкети (№725 п.13) для WTForms.

Єдине джерело правди для полів медичного профілю: використовується
анкетою "Дані для сертифіката" в кабінеті (app.auth.forms) та формою
самостійного завершення реєстрації за токеном (app.registration.forms).
Зміна вимог МОЗ вноситься тут один раз.

Окремий модуль (а не registration/forms), щоб auth не імпортував
blueprint-пакет registration і не створював прихованих ланцюжків імпортів.
"""
from datetime import date

from wtforms import DateField, SelectField, SelectMultipleField, StringField
from wtforms.validators import DataRequired, Length, ValidationError

from app.models.medical_profile import MedicalProfile
from app.models.specializations import SPECIALIZATIONS


class MedicalProfileFieldsMixin:
    """Поля MedicalProfile для форм. Підмішується ПЕРЕД FlaskForm:
    class MyForm(MedicalProfileFieldsMixin, FlaskForm)."""

    user_type = SelectField(
        'Тип учасника',
        choices=[('', '— оберіть —')] + MedicalProfile.PARTICIPANT_TYPES,
        validators=[DataRequired(message='Оберіть тип учасника')],
    )
    middle_name = StringField(
        'По батькові',
        validators=[DataRequired(message='По батькові обов\'язкове'), Length(max=100)],
        render_kw={'autocomplete': 'additional-name'},
    )
    birth_date = DateField(
        'Дата народження',
        validators=[DataRequired(message='Дата народження обов\'язкова')],
        render_kw={'autocomplete': 'bday'},
    )
    education = StringField(
        'Освіта (рік закінчення та назва ВНЗ)',
        validators=[DataRequired(message='Освіта обов\'язкова'), Length(max=500)],
        render_kw={'placeholder': '2014, НМУ ім. О.О. Богомольця'},
    )
    workplace = StringField(
        'Місце роботи (назва ЗОЗу)',
        validators=[DataRequired(message='Місце роботи обов\'язкове'), Length(max=300)],
        render_kw={'autocomplete': 'organization'},
    )
    position = StringField(
        'Займана посада',
        validators=[DataRequired(message='Займана посада обов\'язкова'), Length(max=200)],
        render_kw={
            'placeholder': 'асистент, лікар-ординатор, головний лікар...',
            'autocomplete': 'organization-title',
        },
    )
    specializations = SelectMultipleField(
        'Спеціалізації',
        choices=SPECIALIZATIONS,
        validators=[DataRequired(message='Оберіть хоча б одну спеціалізацію')],
    )

    def validate_birth_date(self, field):
        if field.data is None:
            return
        if field.data > date.today():
            raise ValidationError('Дата народження не може бути в майбутньому')
        if field.data.year < 1900:
            raise ValidationError('Некоректний рік народження')
