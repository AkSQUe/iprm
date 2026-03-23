from flask_wtf import FlaskForm
from wtforms import (
    StringField, TextAreaField, SelectField, IntegerField,
    DecimalField, BooleanField, DateTimeLocalField
)
from wtforms.validators import DataRequired, Length, Optional, NumberRange
from app.models.event import Event


class TrainerForm(FlaskForm):
    full_name = StringField(
        'ПІБ',
        validators=[DataRequired(message='ПІБ обов\'язкове'), Length(max=200)],
    )
    slug = StringField(
        'Slug (URL)',
        validators=[DataRequired(message='Slug обов\'язковий'), Length(max=200)],
    )
    role = StringField(
        'Посада / спеціалізація',
        validators=[Optional(), Length(max=300)],
    )
    bio = TextAreaField(
        'Біографія',
        validators=[Optional()],
    )
    photo = StringField(
        'Фото (URL)',
        validators=[Optional(), Length(max=500)],
    )
    experience_years = IntegerField(
        'Стаж (років)',
        validators=[Optional(), NumberRange(min=0)],
    )
    is_active = BooleanField('Активний', default=True)


class EventForm(FlaskForm):
    title = StringField(
        'Назва заходу',
        validators=[DataRequired(message='Назва обов\'язкова'), Length(max=255)],
    )
    subtitle = StringField(
        'Підзаголовок',
        validators=[Optional(), Length(max=500)],
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
        choices=Event.EVENT_TYPES,
        validators=[DataRequired()],
    )
    event_format = SelectField(
        'Формат',
        choices=Event.FORMATS,
        validators=[DataRequired()],
    )
    status = SelectField(
        'Статус',
        choices=Event.STATUSES,
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
    hero_image = StringField(
        'Hero зображення (URL)',
        validators=[Optional(), Length(max=500)],
    )
    card_image = StringField(
        'Зображення картки (URL)',
        validators=[Optional(), Length(max=500)],
    )
    cpd_points = IntegerField(
        'CPD балів',
        validators=[Optional(), NumberRange(min=0)],
    )
    trainer_id = SelectField(
        'Тренер',
        coerce=int,
        validators=[Optional()],
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
