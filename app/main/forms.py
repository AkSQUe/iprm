from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional


class ContactForm(FlaskForm):
    name = StringField(
        'name',
        validators=[
            DataRequired(message='Будь ласка, вкажіть ваше ім\'я'),
            Length(max=100, message='Ім\'я не може перевищувати 100 символів'),
        ],
        render_kw={
            'placeholder': 'Ваше ім\'я',
            'autocomplete': 'name',
        },
    )
    email = StringField(
        'email',
        validators=[
            DataRequired(message='Будь ласка, вкажіть email'),
            Email(message='Невірний формат email'),
            Length(max=200, message='Email не може перевищувати 200 символів'),
        ],
        render_kw={
            'placeholder': 'email@example.com',
            'autocomplete': 'email',
        },
    )
    phone = StringField(
        'phone',
        validators=[
            Optional(),
            Length(max=20, message='Телефон не може перевищувати 20 символів'),
        ],
        render_kw={
            'placeholder': '+380XXXXXXXXX',
            'autocomplete': 'tel',
        },
    )
    subject = StringField(
        'subject',
        validators=[
            Optional(),
            Length(max=200, message='Тема не може перевищувати 200 символів'),
        ],
        render_kw={
            'placeholder': 'Тема повідомлення',
        },
    )
    message = TextAreaField(
        'message',
        validators=[
            DataRequired(message='Будь ласка, введіть повідомлення'),
            Length(
                min=10,
                max=5000,
                message='Повідомлення має бути від 10 до 5000 символів',
            ),
        ],
        render_kw={
            'placeholder': 'Ваше повідомлення...',
            'rows': 6,
        },
    )
    consent_data = BooleanField(
        'consent_data',
        validators=[
            DataRequired(
                message='Необхідно надати згоду на обробку персональних даних'
            ),
        ],
    )
