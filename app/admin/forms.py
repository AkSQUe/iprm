from flask_wtf import FlaskForm
from wtforms import (
    StringField, TextAreaField, SelectField, IntegerField,
    DecimalField, BooleanField, DateTimeLocalField
)
from wtforms.validators import DataRequired, Length, Optional, NumberRange


class EventForm(FlaskForm):
    title = StringField(
        'Назва заходу',
        validators=[DataRequired(message='Назва обов\'язкова'), Length(max=255)],
    )
    slug = StringField(
        'Slug (URL)',
        validators=[DataRequired(message='Slug обов\'язковий'), Length(max=200)],
    )
    short_description = TextAreaField(
        'Короткий опис',
        validators=[Optional(), Length(max=500)],
    )
    description = TextAreaField(
        'Повний опис',
        validators=[Optional()],
    )
    event_type = SelectField(
        'Тип заходу',
        choices=[
            ('seminar', 'Семінар'),
            ('webinar', 'Вебінар'),
            ('course', 'Курс'),
            ('masterclass', 'Майстер-клас'),
            ('conference', 'Конференція'),
        ],
        validators=[DataRequired()],
    )
    format = SelectField(
        'Формат',
        choices=[
            ('online', 'Онлайн'),
            ('offline', 'Офлайн'),
            ('hybrid', 'Гібрид'),
        ],
        validators=[DataRequired()],
    )
    status = SelectField(
        'Статус',
        choices=[
            ('draft', 'Чернетка'),
            ('published', 'Опубліковано'),
            ('active', 'Активний'),
            ('completed', 'Завершено'),
            ('cancelled', 'Скасовано'),
        ],
        validators=[DataRequired()],
    )
    start_date = DateTimeLocalField(
        'Дата початку',
        format='%Y-%m-%dT%H:%M',
        validators=[DataRequired(message='Дата початку обов\'язкова')],
    )
    end_date = DateTimeLocalField(
        'Дата закінчення',
        format='%Y-%m-%dT%H:%M',
        validators=[Optional()],
    )
    max_participants = IntegerField(
        'Макс. учасників',
        validators=[Optional(), NumberRange(min=1)],
    )
    price = DecimalField(
        'Ціна (UAH)',
        default=0,
        validators=[Optional(), NumberRange(min=0)],
    )
    location = StringField(
        'Локація',
        validators=[Optional(), Length(max=255)],
    )
    online_link = StringField(
        'Посилання на онлайн',
        validators=[Optional(), Length(max=500)],
    )
    speaker_info = TextAreaField(
        'Інформація про спікера',
        validators=[Optional()],
    )
    agenda = TextAreaField(
        'Програма заходу',
        validators=[Optional()],
    )
    is_featured = BooleanField('Рекомендований')
