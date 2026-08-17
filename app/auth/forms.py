from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from app.forms_medical import MedicalProfileFieldsMixin
from app.models.user import User


class CertificateDataForm(MedicalProfileFieldsMixin, FlaskForm):
    """Анкета "Дані для сертифіката" (МОЗ №725 п.13) в особистому кабінеті.

    Винесена за рамки flow реєстрації/оплати (рішення 08.07.2026):
    заповнення -- умова отримання сертифіката з балами БПР, а не участі.
    Усі поля -- з MedicalProfileFieldsMixin (спільні з формою завершення
    реєстрації за токеном)."""


class LoginForm(FlaskForm):
    email = StringField(
        'Email',
        validators=[
            DataRequired(message=_l('Email обов\'язковий')),
        ],
        render_kw={
            'placeholder': 'ваш.email@example.com',
            'autocomplete': 'email',
        }
    )
    password = PasswordField(
        _l('Пароль'),
        validators=[
            DataRequired(message=_l('Пароль обов\'язковий')),
        ],
        render_kw={
            'placeholder': _l('Введіть ваш пароль'),
            'autocomplete': 'current-password',
        }
    )
    remember = BooleanField(_l('Запам\'ятати мене'))


class RegistrationForm(FlaskForm):
    email = StringField(
        'Email',
        validators=[
            DataRequired(message=_l('Email обов\'язковий')),
            Email(message=_l('Невірний формат email')),
            Length(max=255, message=_l('Email занадто довгий')),
        ],
        render_kw={
            'placeholder': 'ваш.email@example.com',
            'autocomplete': 'email',
        }
    )
    first_name = StringField(
        _l('Ім\'я'),
        validators=[
            DataRequired(message=_l('Ім\'я обов\'язкове')),
            Length(min=2, max=100, message=_l('Ім\'я повинно бути від 2 до 100 символів')),
        ],
        render_kw={
            'placeholder': _l('Ваше ім\'я'),
        }
    )
    last_name = StringField(
        _l('Прізвище'),
        validators=[
            DataRequired(message=_l('Прізвище обов\'язкове')),
            Length(min=2, max=100, message=_l('Прізвище повинно бути від 2 до 100 символів')),
        ],
        render_kw={
            'placeholder': _l('Ваше прізвище'),
        }
    )
    password = PasswordField(
        _l('Пароль'),
        validators=[
            DataRequired(message=_l('Пароль обов\'язковий')),
            Length(min=8, max=128, message=_l('Пароль повинен бути від 8 до 128 символів')),
        ],
        render_kw={
            'placeholder': _l('Мінімум 8 символів'),
            'autocomplete': 'new-password',
        }
    )
    password_confirm = PasswordField(
        _l('Підтвердження паролю'),
        validators=[
            DataRequired(message=_l('Підтвердження паролю обов\'язкове')),
            EqualTo('password', message=_l('Паролі не співпадають')),
        ],
        render_kw={
            'placeholder': _l('Повторіть пароль'),
            'autocomplete': 'new-password',
        }
    )

    consent_data = BooleanField(
        validators=[DataRequired(message=_l('Необхідно надати згоду на обробку персональних даних'))],
    )

    def validate_email(self, field):
        # Підказуємо дію, не підтверджуючи існування акаунта прямо:
        # частина адрес -- імпортовані учасники без пароля, для яких
        # правильний шлях саме "Забули пароль" або вхід через Google.
        if User.query.filter_by(email=field.data.lower().strip()).first():
            raise ValidationError(_(
                'Неможливо використати цей email. Якщо обліковий запис уже '
                'існує – увійдіть, відновіть пароль або скористайтесь '
                'входом через Google.'
            ))


class ForgotPasswordForm(FlaskForm):
    email = StringField(
        'Email',
        validators=[
            DataRequired(message=_l('Email обов\'язковий')),
            Email(message=_l('Невірний формат email')),
            Length(max=255, message=_l('Email занадто довгий')),
        ],
        render_kw={
            'placeholder': 'ваш.email@example.com',
            'autocomplete': 'email',
        }
    )


class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        _l('Новий пароль'),
        validators=[
            DataRequired(message=_l('Пароль обов\'язковий')),
            Length(min=8, max=128, message=_l('Пароль повинен бути від 8 до 128 символів')),
        ],
        render_kw={
            'placeholder': _l('Мінімум 8 символів'),
            'autocomplete': 'new-password',
        }
    )
    password_confirm = PasswordField(
        _l('Підтвердження паролю'),
        validators=[
            DataRequired(message=_l('Підтвердження паролю обов\'язкове')),
            EqualTo('password', message=_l('Паролі не співпадають')),
        ],
        render_kw={
            'placeholder': _l('Повторіть пароль'),
            'autocomplete': 'new-password',
        }
    )
