from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError
from app.models.user import User


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
