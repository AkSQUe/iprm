from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, BooleanField, DateField, SelectField,
    SelectMultipleField,
)
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from app.models.medical_profile import MedicalProfile
from app.models.specializations import SPECIALIZATIONS
from app.models.user import User


class CertificateDataForm(FlaskForm):
    """Анкета "Дані для сертифіката" (МОЗ №725 п.13) в особистому кабінеті.

    Винесена за рамки flow реєстрації/оплати (рішення 08.07.2026):
    заповнення -- умова отримання сертифіката з балами БПР, а не участі.
    """
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


class LoginForm(FlaskForm):
    email = StringField(
        'Email',
        validators=[
            DataRequired(message='Email обов\'язковий'),
        ],
        render_kw={
            'placeholder': 'ваш.email@example.com',
            'autocomplete': 'email',
        }
    )
    password = PasswordField(
        'Пароль',
        validators=[
            DataRequired(message='Пароль обов\'язковий'),
        ],
        render_kw={
            'placeholder': 'Введіть ваш пароль',
            'autocomplete': 'current-password',
        }
    )
    remember = BooleanField('Запам\'ятати мене')


class RegistrationForm(FlaskForm):
    email = StringField(
        'Email',
        validators=[
            DataRequired(message='Email обов\'язковий'),
            Email(message='Невірний формат email'),
            Length(max=255, message='Email занадто довгий'),
        ],
        render_kw={
            'placeholder': 'ваш.email@example.com',
            'autocomplete': 'email',
        }
    )
    first_name = StringField(
        'Ім\'я',
        validators=[
            DataRequired(message='Ім\'я обов\'язкове'),
            Length(min=2, max=100, message='Ім\'я повинно бути від 2 до 100 символів'),
        ],
        render_kw={
            'placeholder': 'Ваше ім\'я',
        }
    )
    last_name = StringField(
        'Прізвище',
        validators=[
            DataRequired(message='Прізвище обов\'язкове'),
            Length(min=2, max=100, message='Прізвище повинно бути від 2 до 100 символів'),
        ],
        render_kw={
            'placeholder': 'Ваше прізвище',
        }
    )
    password = PasswordField(
        'Пароль',
        validators=[
            DataRequired(message='Пароль обов\'язковий'),
            Length(min=8, max=128, message='Пароль повинен бути від 8 до 128 символів'),
        ],
        render_kw={
            'placeholder': 'Мінімум 8 символів',
            'autocomplete': 'new-password',
        }
    )
    password_confirm = PasswordField(
        'Підтвердження паролю',
        validators=[
            DataRequired(message='Підтвердження паролю обов\'язкове'),
            EqualTo('password', message='Паролі не співпадають'),
        ],
        render_kw={
            'placeholder': 'Повторіть пароль',
            'autocomplete': 'new-password',
        }
    )

    consent_data = BooleanField(
        validators=[DataRequired(message='Необхідно надати згоду на обробку персональних даних')],
    )

    def validate_email(self, field):
        if User.query.filter_by(email=field.data.lower().strip()).first():
            raise ValidationError('Неможливо використати цей email')


class ForgotPasswordForm(FlaskForm):
    email = StringField(
        'Email',
        validators=[
            DataRequired(message='Email обов\'язковий'),
            Email(message='Невірний формат email'),
            Length(max=255, message='Email занадто довгий'),
        ],
        render_kw={
            'placeholder': 'ваш.email@example.com',
            'autocomplete': 'email',
        }
    )


class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        'Новий пароль',
        validators=[
            DataRequired(message='Пароль обов\'язковий'),
            Length(min=8, max=128, message='Пароль повинен бути від 8 до 128 символів'),
        ],
        render_kw={
            'placeholder': 'Мінімум 8 символів',
            'autocomplete': 'new-password',
        }
    )
    password_confirm = PasswordField(
        'Підтвердження паролю',
        validators=[
            DataRequired(message='Підтвердження паролю обов\'язкове'),
            EqualTo('password', message='Паролі не співпадають'),
        ],
        render_kw={
            'placeholder': 'Повторіть пароль',
            'autocomplete': 'new-password',
        }
    )
