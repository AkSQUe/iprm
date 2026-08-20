"""Спільні поля анкети учасника (МОЗ №725 п.13 + ПІБ) для WTForms.

Єдине джерело правди для полів медичного профілю та ПІБ: використовується
анкетою "Дані для сертифіката" в кабінеті (app.auth.forms) та формою
самостійного завершення реєстрації за токеном (app.registration.forms).
Зміна вимог МОЗ вноситься тут один раз.

Окремий модуль (а не registration/forms), щоб auth не імпортував
blueprint-пакет registration і не створював прихованих ланцюжків імпортів.
"""
from datetime import date

from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l
from wtforms import DateField, SelectField, SelectMultipleField, StringField
from wtforms.validators import DataRequired, Length, ValidationError

from app.models.medical_profile import MedicalProfile
from app.models.specializations import localized_specializations


class MedicalProfileFieldsMixin:
    """Поля MedicalProfile для форм. Підмішується ПЕРЕД FlaskForm:
    class MyForm(MedicalProfileFieldsMixin, FlaskForm)."""

    user_type = SelectField(
        _l('Тип учасника'),
        choices=[('', _l('— оберіть —'))] + MedicalProfile.PARTICIPANT_TYPES,
        validators=[DataRequired(message=_l('Оберіть тип учасника'))],
    )
    middle_name = StringField(
        _l('По батькові'),
        validators=[DataRequired(message=_l('По батькові обов\'язкове')), Length(max=100)],
        render_kw={'autocomplete': 'additional-name'},
    )
    birth_date = DateField(
        _l('Дата народження'),
        validators=[DataRequired(message=_l('Дата народження обов\'язкова'))],
        render_kw={'autocomplete': 'bday'},
    )
    education = StringField(
        _l('Освіта (рік закінчення та назва ВНЗ)'),
        validators=[DataRequired(message=_l('Освіта обов\'язкова')), Length(max=500)],
        render_kw={'placeholder': _l('2014, НМУ ім. О.О. Богомольця')},
    )
    workplace = StringField(
        _l('Місце роботи (назва ЗОЗу)'),
        validators=[DataRequired(message=_l('Місце роботи обов\'язкове')), Length(max=300)],
        render_kw={'autocomplete': 'organization'},
    )
    position = StringField(
        _l('Займана посада'),
        validators=[DataRequired(message=_l('Займана посада обов\'язкова')), Length(max=200)],
        render_kw={
            'placeholder': _l('асистент, лікар-ординатор, головний лікар...'),
            'autocomplete': 'organization-title',
        },
    )
    specializations = SelectMultipleField(
        _l('Спеціалізації'),
        # Callable -> labels перекладаються на льоту при інстанціюванні форми;
        # канонічний список (для БД/XLSX) лишається незмінним.
        choices=localized_specializations,
        validators=[DataRequired(message=_l('Оберіть хоча б одну спеціалізацію'))],
    )

    def validate_birth_date(self, field):
        if field.data is None:
            return
        if field.data > date.today():
            raise ValidationError(_('Дата народження не може бути в майбутньому'))
        if field.data.year < 1900:
            raise ValidationError(_('Некоректний рік народження'))


class UserNameFieldsMixin:
    """Прізвище та ім'я з `User` для форм, що редагують ПІБ.

    Окремо від `MedicalProfileFieldsMixin`: ці два поля зберігаються в
    `users`, а не в `medical_profiles`, і змішувати їх в одному міксині
    означало б збрехати про джерело даних. Спільний міксин потрібен, бо
    анкета в кабінеті й форма завершення реєстрації за токеном мають
    однаково валідувати ПІБ -- інакше вони розійдуться при першій же
    зміні валідатора.

    Підмішується ПЕРЕД FlaskForm, як і сусідній міксин.
    """

    last_name = StringField(
        _l('Прізвище'),
        validators=[DataRequired(message=_l('Прізвище обов\'язкове')), Length(max=100)],
        render_kw={'autocomplete': 'family-name'},
    )
    first_name = StringField(
        _l('Ім\'я'),
        validators=[DataRequired(message=_l('Ім\'я обов\'язкове')), Length(max=100)],
        render_kw={'autocomplete': 'given-name'},
    )
