from flask_wtf import FlaskForm
from wtforms import (
    StringField, TextAreaField, SelectField, IntegerField,
    DecimalField, BooleanField, DateTimeLocalField, HiddenField
)
from wtforms.validators import DataRequired, Length, Optional, NumberRange, Email
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_request import CourseRequest


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


class SiteSettingsForm(FlaskForm):
    # Company info
    company_name = StringField(
        'Коротка назва',
        validators=[DataRequired(message='Назва обов\'язкова'), Length(max=100)],
    )
    company_full_name = StringField(
        'Повна назва',
        validators=[Optional(), Length(max=500)],
    )
    company_legal_name = StringField(
        'Юридична назва',
        validators=[Optional(), Length(max=500)],
    )
    edrpou = StringField(
        'Код ЄДРПОУ',
        validators=[Optional(), Length(max=20)],
    )

    # Contacts
    phone_primary = StringField(
        'Основний телефон',
        validators=[Optional(), Length(max=50)],
    )
    phone_secondary = StringField(
        'Додатковий телефон',
        validators=[Optional(), Length(max=50)],
    )
    email = StringField(
        'Email',
        validators=[Optional(), Length(max=255)],
    )
    address = TextAreaField(
        'Адреса',
        validators=[Optional()],
    )
    city = StringField(
        'Місто',
        validators=[Optional(), Length(max=200)],
    )

    # Social media
    facebook_url = StringField(
        'Facebook',
        validators=[Optional(), Length(max=500)],
    )
    instagram_url = StringField(
        'Instagram',
        validators=[Optional(), Length(max=500)],
    )
    telegram_url = StringField(
        'Telegram',
        validators=[Optional(), Length(max=500)],
    )

    # Business
    business_hours = StringField(
        'Графік роботи',
        validators=[Optional(), Length(max=200)],
    )
    website_url = StringField(
        'Вебсайт',
        validators=[Optional(), Length(max=500)],
    )

    # Секції навігації
    show_labs = BooleanField('Показувати розділ "Лабораторії"', default=True)
    show_clinics = BooleanField('Показувати розділ "Клініки"', default=True)

    # Partner integration (MM Medic та інші)
    partner_integration_enabled = BooleanField(
        'Увімкнути інтеграцію з партнерськими сайтами',
        default=False,
    )
    partner_api_key = StringField(
        'API-ключ для партнерів',
        validators=[Optional(), Length(max=255)],
        description=(
            'Використовується партнерськими сайтами у заголовку X-API-Key '
            'при запитах до /api/v1/events. '
            'Залиште порожнім, щоб не змінювати поточне значення.'
        ),
    )
    partner_prefill_secret = StringField(
        'Секрет для підписаних токенів реєстрації',
        validators=[Optional(), Length(max=255)],
        description=(
            'HS256-ключ, яким партнерські сайти підписують JWT для '
            'автоматичної передачі даних користувача. '
            'Залиште порожнім, щоб не змінювати. '
            'Рекомендована довжина: 64+ символи.'
        ),
    )
    partner_webhook_enabled = BooleanField(
        'Надсилати webhook при зміні заходів',
        default=False,
    )
    partner_webhook_url = StringField(
        'URL webhook партнера',
        validators=[Optional(), Length(max=500)],
        description=(
            'HTTPS URL на партнерському сайті, куди IPRM POST-ить '
            'подію при створенні/зміні/видаленні заходу. '
            'Напр. https://mm-medic.com/api/webhooks/iprm/events'
        ),
    )
    partner_webhook_secret = StringField(
        'Секрет підпису webhook',
        validators=[Optional(), Length(max=255)],
        description=(
            'HMAC-SHA256 ключ, яким IPRM підписує webhook-тіло. '
            'Має збігатися з секретом на партнерському сайті. '
            'Залиште порожнім, щоб не змінювати. Рекомендовано: 64+ hex символи.'
        ),
    )


# ========== COURSES / INSTANCES / REQUESTS ==========

class CourseForm(FlaskForm):
    """Каталог: що за курс (без дати)."""
    title = StringField(
        'Назва курсу',
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
        'Тип',
        choices=Course.EVENT_TYPES,
        validators=[DataRequired()],
    )
    hero_image = StringField(
        'Hero зображення (URL)',
        validators=[Optional(), Length(max=500)],
    )
    card_image = StringField(
        'Зображення картки (URL)',
        validators=[Optional(), Length(max=500)],
    )
    target_audience_text = TextAreaField(
        'Цільова аудиторія',
        validators=[Optional()],
        description='Один пункт на рядок',
    )
    tags_text = TextAreaField(
        'Теги',
        validators=[Optional()],
        description='Один тег на рядок',
    )
    speaker_info = TextAreaField(
        'Інформація про спікера',
        validators=[Optional()],
    )
    agenda = TextAreaField(
        'Програма (загальний опис)',
        validators=[Optional()],
    )
    faq_text = TextAreaField(
        'FAQ',
        validators=[Optional()],
        description='Формат: Питання?\\nВідповідь\\n\\nПитання?\\nВідповідь',
    )
    base_price = DecimalField(
        'Базова ціна (UAH)',
        default=0,
        validators=[Optional(), NumberRange(min=0)],
        description='Default-ціна; конкретне проведення може перевизначити',
    )
    cpd_points = IntegerField(
        'Бали БПР (default)',
        validators=[Optional(), NumberRange(min=0)],
    )
    max_participants = IntegerField(
        'Макс. учасників (default)',
        validators=[Optional(), NumberRange(min=1)],
    )
    trainer_id = SelectField(
        'Тренер (default)',
        coerce=int,
        validators=[Optional()],
    )
    is_active = BooleanField('Активний у каталозі', default=True)
    is_featured = BooleanField('Рекомендований')


class CourseInstanceForm(FlaskForm):
    """Проведення: коли, де, в якому форматі."""
    course_id = SelectField(
        'Курс',
        coerce=int,
        validators=[DataRequired(message='Оберіть курс')],
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
    event_format = SelectField(
        'Формат',
        choices=CourseInstance.FORMATS,
        validators=[DataRequired()],
    )
    status = SelectField(
        'Статус',
        choices=CourseInstance.STATUSES,
        validators=[DataRequired()],
    )
    price = DecimalField(
        'Ціна (UAH)',
        validators=[Optional(), NumberRange(min=0)],
        description='Залиште порожнім щоб взяти базову ціну курсу',
    )
    cpd_points = IntegerField(
        'Бали БПР',
        validators=[Optional(), NumberRange(min=0)],
        description='Залиште порожнім щоб взяти з курсу',
    )
    max_participants = IntegerField(
        'Макс. учасників',
        validators=[Optional(), NumberRange(min=1)],
        description='Залиште порожнім щоб взяти з курсу',
    )
    location = StringField(
        'Локація',
        validators=[Optional(), Length(max=255)],
    )
    online_link = StringField(
        'Посилання на онлайн',
        validators=[Optional(), Length(max=500)],
    )
    trainer_id = SelectField(
        'Тренер',
        coerce=int,
        validators=[Optional()],
        description='Залиште порожнім щоб взяти default-тренера курсу',
    )


class CourseRequestForm(FlaskForm):
    """Публічна форма: залишити запит на проведення курсу."""
    email = StringField(
        'Email',
        validators=[
            DataRequired(message='Email обов\'язковий'),
            Email(message='Невалідний email'),
            Length(max=255),
        ],
    )
    phone = StringField(
        'Телефон',
        validators=[Optional(), Length(max=20)],
    )
    message = TextAreaField(
        'Повідомлення',
        validators=[Optional(), Length(max=1000)],
        description='Опціонально: опишіть чому вам важливий цей курс',
    )


class CourseRequestAdminForm(FlaskForm):
    """Адмінська форма: обробити запит."""
    status = SelectField(
        'Статус',
        choices=CourseRequest.STATUSES,
        validators=[DataRequired()],
    )
    admin_notes = TextAreaField(
        'Нотатки адміна',
        validators=[Optional()],
    )
