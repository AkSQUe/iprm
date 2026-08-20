from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional


class ContactForm(FlaskForm):
    name = StringField(
        'name',
        validators=[
            DataRequired(message=_l('Будь ласка, вкажіть ваше ім\'я')),
            Length(max=100, message=_l('Ім\'я не може перевищувати 100 символів')),
        ],
        render_kw={
            'placeholder': _l('Ваше ім\'я'),
            'autocomplete': 'name',
        },
    )
    email = StringField(
        'email',
        validators=[
            DataRequired(message=_l('Будь ласка, вкажіть email')),
            Email(message=_l('Невірний формат email')),
            Length(max=200, message=_l('Email не може перевищувати 200 символів')),
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
            Length(max=20, message=_l('Телефон не може перевищувати 20 символів')),
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
            Length(max=200, message=_l('Тема не може перевищувати 200 символів')),
        ],
        render_kw={
            'placeholder': _l('Тема повідомлення'),
        },
    )
    message = TextAreaField(
        'message',
        validators=[
            DataRequired(message=_l('Будь ласка, введіть повідомлення')),
            Length(
                min=10,
                max=5000,
                message=_l('Повідомлення має бути від 10 до 5000 символів'),
            ),
        ],
        render_kw={
            'placeholder': _l('Ваше повідомлення...'),
            'rows': 6,
        },
    )
    consent_data = BooleanField(
        'consent_data',
        validators=[
            DataRequired(
                message=_l('Необхідно надати згоду на обробку персональних даних')
            ),
        ],
    )


class TrainerConfirmForm(FlaskForm):
    """Тренер підтверджує комплект матеріалів на публічній сторінці
    `/materials/<token>`. Одна дія -- підтвердження; коментар вільний і
    необов'язковий (тренер, що дописав «ще треба голок», підтвердив і
    повідомив одночасно, а не обирав між двома кнопками)."""
    comment = TextAreaField(
        'comment',
        validators=[
            Optional(),
            Length(max=2000, message=_l('Коментар не може перевищувати 2000 символів')),
        ],
        render_kw={
            'placeholder': _l('Якщо чогось бракує -- напишіть тут (необов\'язково)'),
            'rows': 4,
        },
    )
