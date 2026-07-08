from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    StringField, BooleanField, DateField,
    SelectField, SelectMultipleField,
)
from wtforms.validators import (
    DataRequired, Length, Email, ValidationError,
)

from app.models.medical_profile import MedicalProfile
from app.models.specializations import SPECIALIZATIONS


class EventRegistrationForm(FlaskForm):
    """Реєстрація на CourseInstance -- ЛИШЕ базова інформація.

    Медична анкета (МОЗ України №725 п.13: тип учасника, дата народження,
    освіта, спеціалізації тощо) винесена ЗА рамки flow оплати -- учасник
    заповнює її в особистому кабінеті (auth.certificate_data), це умова
    отримання сертифіката, а не реєстрації. Рішення 08.07.2026.
    """
    # ----- ПІБ -----
    # last_name + first_name беруться з User (signup), але показуємо їх на
    # формі для редагування. Якщо змінились -- оновимо User у роуті.
    last_name = StringField(
        'Прізвище',
        validators=[DataRequired(message='Прізвище обов\'язкове'), Length(max=100)],
        render_kw={'autocomplete': 'family-name'},
    )
    first_name = StringField(
        'Ім\'я',
        validators=[DataRequired(message='Ім\'я обов\'язкове'), Length(max=100)],
        render_kw={'autocomplete': 'given-name'},
    )

    # ----- Контакт -----
    phone = StringField(
        'Телефон',
        validators=[DataRequired(message='Телефон обов\'язковий'), Length(max=20)],
        render_kw={'placeholder': '+380XXXXXXXXX', 'autocomplete': 'tel'},
    )

    # Спосіб оплати тут НЕ збираємо: для платних подій є окремий крок оплати
    # (confirmation.html / _pay_options), де користувач обирає LiqPay або
    # рахунок безпосередньо дією. reg.payment_method дефолтиться у 'liqpay' і
    # уточнюється фактом завантаження рахунка.

    # ----- Згоди (GDPR) -----
    consent_data = BooleanField(
        validators=[DataRequired(message='Необхідно надати згоду на обробку персональних даних')],
    )
    consent_marketing = BooleanField()


class ParticipantCompletionForm(FlaskForm):
    """Публічна форма самостійного завершення реєстрації за токеном.

    Учасник заповнює анкету повністю -- УСІ поля обов'язкові (на відміну від
    admin-форми, де частина опціональна). Реєстраційні/адмін-поля (статус,
    оплата, бали) сюди не виносяться -- ними керує менеджер."""
    user_type = SelectField(
        'Тип учасника',
        choices=[('', '— оберіть —')] + MedicalProfile.PARTICIPANT_TYPES,
        validators=[DataRequired(message='Оберіть тип учасника')],
    )
    last_name = StringField(
        'Прізвище',
        validators=[DataRequired(message='Прізвище обов\'язкове'), Length(max=100)],
        render_kw={'autocomplete': 'family-name'},
    )
    first_name = StringField(
        'Ім\'я',
        validators=[DataRequired(message='Ім\'я обов\'язкове'), Length(max=100)],
        render_kw={'autocomplete': 'given-name'},
    )
    middle_name = StringField(
        'По батькові',
        validators=[DataRequired(message='По батькові обов\'язкове'), Length(max=100)],
        render_kw={'autocomplete': 'additional-name'},
    )
    email = StringField(
        'Email',
        validators=[
            DataRequired(message='Email обов\'язковий'),
            Email(message='Невалідний email'),
            Length(max=255),
        ],
        render_kw={'autocomplete': 'email'},
    )
    phone = StringField(
        'Телефон',
        validators=[DataRequired(message='Телефон обов\'язковий'), Length(max=20)],
        render_kw={'placeholder': '+380XXXXXXXXX', 'autocomplete': 'tel'},
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
        render_kw={'autocomplete': 'organization-title'},
    )
    specializations = SelectMultipleField(
        'Спеціалізації',
        choices=SPECIALIZATIONS,
        validators=[DataRequired(message='Оберіть хоча б одну спеціалізацію')],
    )
    consent_data = BooleanField(
        validators=[DataRequired(message='Необхідно надати згоду на обробку персональних даних')],
    )

    def validate_birth_date(self, field):
        if field.data is None:
            return
        if field.data > date.today():
            raise ValidationError('Дата народження не може бути в майбутньому')
        if field.data.year < 1900:
            raise ValidationError('Некоректний рік народження')
