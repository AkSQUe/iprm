from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    StringField, TextAreaField, SelectField, SelectMultipleField, IntegerField,
    DecimalField, BooleanField, DateField, DateTimeLocalField, HiddenField
)
from wtforms.validators import (
    DataRequired, InputRequired, Length, Optional, NumberRange, Email, URL,
    ValidationError, Regexp,
)
from app.utils import (
    normalize_name, normalize_phone, UA_PHONE_RE, CYRILLIC_NAME_RE,
)
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_request import CourseRequest
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.specializations import SPECIALIZATIONS


def _optional_url(message='Невалідний URL'):
    """URL-валідатор, що приймає або повний URL (http/https), або
    відносний шлях, що починається з '/'.

    Для зображень курсу/тренера ми зберігаємо саме relative paths
    типу /static/images/courses/<slug>/file.webp -- це не валідні URL за
    require_tld, тому стандартний URL-валідатор тут НЕ підходить.
    Порожнє значення короткозамикається Optional() у списку валідаторів
    (тут не торкаємось).
    """
    abs_url = URL(require_tld=True, message=message)

    def _check(form, field):
        value = (field.data or '').strip()
        if not value:
            return
        if value.startswith('/'):
            # відносний шлях від кореня сайту -- OK
            return
        abs_url(form, field)

    return _check


class TrainerForm(FlaskForm):
    full_name = StringField(
        'ПІБ',
        validators=[DataRequired(message='ПІБ обов\'язкове'), Length(max=200)],
    )
    full_name_dative = StringField(
        'ПІБ у давальному відмінку (для серта лектора, напр. "Гусак Валерії")',
        validators=[Optional(), Length(max=200)],
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
    # media_id фото з реєстру (заповнює dropzone). Рядок -> int у routes.
    photo_media_id = HiddenField('Фото (media)', validators=[Optional()])
    signature = StringField(
        'Підпис (шлях відносно static, напр. images/trainers/slug/signature.webp)',
        validators=[Optional(), Length(max=500)],
    )
    experience_years = IntegerField(
        'Стаж (років)',
        validators=[Optional(), NumberRange(min=0)],
    )
    email = StringField(
        'Email (для admin-сповіщень)',
        validators=[Optional(), Email(message='Невалідний email'), Length(max=255)],
    )
    is_active = BooleanField('Активний', default=True)
    # Опційні регалії -- JSON із редактора (санітизація у trainer_service).
    certificates = HiddenField()
    patents = HiddenField()
    articles = HiddenField()
    # Наукова та дослідницька діяльність -- один пункт на рядок (textarea).
    research = TextAreaField(
        'Наукова та дослідницька діяльність',
        validators=[Optional()],
    )
    # Додаткові секції профілю -- один пункт на рядок (textarea).
    skills = TextAreaField('Професійні навички', validators=[Optional()])
    education = TextAreaField('Освіта та кваліфікація', validators=[Optional()])
    additional_education = TextAreaField(
        'Додаткова освіта та міжнародне стажування', validators=[Optional()],
    )
    work_experience = TextAreaField('Досвід роботи', validators=[Optional()])


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
    # Банківські реквізити -- для рахунка на оплату.
    bank_iban = StringField(
        'IBAN (розрахунковий рахунок)',
        validators=[Optional(), Length(max=34)],
        description='Напр. UA213052990000026003006239637',
    )
    bank_name = StringField(
        'Назва банку',
        validators=[Optional(), Length(max=255)],
    )
    tax_status = StringField(
        'Податковий статус',
        validators=[Optional(), Length(max=255)],
        description='Напр. Платник єдиного податку третьої групи (неплатник ПДВ).',
    )
    bpr_provider_number = StringField(
        'Реєстраційний номер провайдера БПР',
        validators=[Optional(), Length(max=20)],
        description='4 цифри. Використовується у номері сертифіката (напр. 2738).',
    )
    certificate_format = SelectField(
        'Формат сертифіката',
        choices=[('a4', 'A4 (210x297 мм)'), ('compact', 'Компактний (180x240 мм)')],
        validators=[Optional()],
        description='Розмір сторінки сертифіката. Макет однаковий.',
    )
    show_upcoming_events = BooleanField(
        'Показувати блок «найближчі заходи»',
        description='Плаваючий блок із 2 найближчими майбутніми заходами на публічних сторінках.',
    )
    seats_low_threshold = IntegerField(
        'Поріг «мало місць»',
        default=5,
        validators=[InputRequired(message='Вкажіть поріг (0 вимикає підсвітку)'),
                    NumberRange(min=0, max=1000)],
        description='Коли вільних місць стільки або менше — лічильник підсвічується попередженням. 0 — підсвітку вимкнено.',
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
    mm_medic_integration_enabled = BooleanField(
        'Увімкнути резервування витратних матеріалів MM Medic',
        default=False,
    )
    mm_medic_api_base_url = StringField(
        'Базовий URL API MM Medic',
        validators=[Optional(), Length(max=500)],
        description=(
            'Корінь партнерського API MM Medic для резервування матеріалів. '
            'Напр. https://mm-medic.com. Підпис — тим самим секретом, що й webhook.'
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
    # media_id зображень з реєстру (заповнюють dropzone). Рядок -> int у service.
    hero_media_id = HiddenField('Hero (media)', validators=[Optional()])
    card_media_id = HiddenField('Картка (media)', validators=[Optional()])
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
    bpr_event_number = StringField(
        'Реєстраційний номер заходу БПР',
        validators=[Optional(), Length(max=20)],
        description='7 цифр. Використовується у номері сертифіката (напр. 1028974).',
    )
    bpr_specialties = StringField(
        'Спеціальності (для сертифіката)',
        validators=[Optional(), Length(max=500)],
        description='Напр. "усі лікарські спеціальності". Друкується на сертифікаті.',
    )
    bpr_lecturer_points = IntegerField(
        'Бали БПР лектору',
        validators=[Optional(), NumberRange(min=0)],
        description='Бали, що нараховуються лектору заходу (відрізняються від балів учасника).',
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
        validators=[Optional(), Length(max=500), _optional_url()],
    )
    trainer_id = SelectField(
        'Тренер',
        coerce=int,
        validators=[Optional()],
        description='Залиште порожнім щоб взяти default-тренера курсу',
    )

    def validate_end_date(self, field):
        if field.data and self.start_date.data and field.data <= self.start_date.data:
            raise ValidationError('Дата закінчення має бути пізніше дати початку')


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


class BlogPostForm(FlaskForm):
    """Допис блогу. Контент (блоки) приходить як JSON у прихованому полі
    `content` від блочного редактора; валідується/санітизується у сервісі."""
    title = StringField(
        'Заголовок',
        validators=[DataRequired(message='Вкажіть заголовок'), Length(max=255)],
    )
    slug = StringField(
        'Slug (URL)',
        validators=[Optional(), Length(max=200)],
        description='Автоматично генерується із заголовка, якщо порожньо',
    )
    excerpt = TextAreaField(
        'Короткий опис',
        validators=[Optional(), Length(max=500)],
        description='Для картки в списку та соцмереж. Якщо порожньо -- візьметься з тексту',
    )
    # media_id обкладинки з реєстру (заповнює dropzone). Рядок -> int у routes.
    cover_media_id = HiddenField('Обкладинка (media)', validators=[Optional()])
    content = HiddenField('Контент')
    status = SelectField(
        'Статус',
        choices=[('draft', 'Чернетка'), ('published', 'Опубліковано')],
        validators=[DataRequired()],
    )
    meta_title = StringField(
        'SEO заголовок (title)',
        validators=[Optional(), Length(max=200)],
    )
    meta_description = TextAreaField(
        'SEO опис (meta description)',
        validators=[Optional(), Length(max=500)],
    )


class ParticipantForm(FlaskForm):
    """Ручне додавання/редагування учасника заходу (admin).

    Об'єднує три сутності в одній формі: User (identity), MedicalProfile
    (медичні дані) та EventRegistration (реєстрація на CourseInstance).
    Email НЕ обов'язковий -- менеджер заповнює його пізніше; до того
    користувачу присвоюється placeholder-email (див. routes_participants).

    Більшість полів профілю опціональні: завдання форми -- швидко завести
    учасника, а решту даних дозаповнити згодом через редагування.
    """

    # ----- Захід -----
    # choices заповнюються в роуті. На сторінці, прив'язаній до конкретного
    # заходу, та при редагуванні поле рендериться статично (захід не змінюємо).
    instance_id = SelectField(
        'Захід',
        coerce=int,
        validators=[DataRequired(message='Оберіть захід')],
    )

    # ----- Ідентифікація (User) -----
    # Фільтр нормалізує (кирилиця з великої літери, без CAPS), Regexp вимагає
    # лише українську кирилицю -- щоб менеджер не вводив латиницю/цифри.
    _NAME_CYRILLIC = Regexp(
        CYRILLIC_NAME_RE,
        message='Лише українські літери (кирилиця), напр. «Іваненко».',
    )
    last_name = StringField(
        'Прізвище',
        filters=[normalize_name],
        validators=[DataRequired(message='Прізвище обов\'язкове'), Length(max=100),
                    _NAME_CYRILLIC],
    )
    first_name = StringField(
        'Ім\'я',
        filters=[normalize_name],
        validators=[DataRequired(message='Ім\'я обов\'язкове'), Length(max=100),
                    _NAME_CYRILLIC],
    )
    middle_name = StringField(
        'По батькові',
        filters=[normalize_name],
        validators=[Optional(), Length(max=100), _NAME_CYRILLIC],
    )

    # ----- Контакти -----
    email = StringField(
        'Email',
        filters=[lambda v: v.strip().lower() if isinstance(v, str) else v],
        validators=[Optional(), Email(message='Невалідний email, напр. name@example.com'),
                    Length(max=255)],
        render_kw={'placeholder': 'name@example.com', 'inputmode': 'email',
                   'autocomplete': 'off'},
    )
    phone = StringField(
        'Телефон',
        filters=[normalize_phone],
        validators=[
            DataRequired(message='Телефон обов\'язковий'),
            Regexp(UA_PHONE_RE,
                   message='Телефон у форматі +380XXXXXXXXX (12 цифр).'),
            Length(max=20),
        ],
        render_kw={'placeholder': '+380XXXXXXXXX', 'inputmode': 'tel',
                   'autocomplete': 'off'},
    )

    # ----- Медичний профіль (MedicalProfile) -----
    participant_type = SelectField(
        'Тип учасника',
        choices=[('', '— не вказано —')] + MedicalProfile.PARTICIPANT_TYPES,
        validators=[Optional()],
    )
    birth_date = DateField(
        'Дата народження',
        validators=[Optional()],
    )
    education = StringField(
        'Освіта (рік закінчення та ВНЗ)',
        validators=[Optional(), Length(max=500)],
        render_kw={'placeholder': '2014, НМУ ім. О.О. Богомольця'},
    )
    workplace = StringField(
        'Місце роботи / місто',
        validators=[Optional(), Length(max=300)],
    )
    position = StringField(
        'Посада',
        validators=[Optional(), Length(max=200)],
    )
    specializations = SelectMultipleField(
        'Спеціалізації',
        choices=SPECIALIZATIONS,
        validators=[Optional()],
    )

    # ----- Реєстрація (EventRegistration) -----
    status = SelectField(
        'Статус реєстрації',
        choices=EventRegistration.STATUSES,
        default='confirmed',
        validators=[DataRequired()],
    )
    payment_status = SelectField(
        'Статус оплати',
        choices=EventRegistration.PAYMENT_STATUSES,
        default='unpaid',
        validators=[DataRequired()],
    )
    payment_amount = DecimalField(
        'Сума оплати (UAH)',
        validators=[Optional(), NumberRange(min=0)],
        places=2,
    )
    attended = BooleanField('Був присутній')
    cpd_points_awarded = IntegerField(
        'Нараховані бали БПР',
        validators=[Optional(), NumberRange(min=0)],
    )
    experience_years = IntegerField(
        'Стаж (років)',
        validators=[Optional(), NumberRange(min=0, max=70)],
    )
    license_number = StringField(
        'Номер ліцензії',
        validators=[Optional(), Length(max=50)],
    )
    admin_notes = TextAreaField(
        'Нотатки адміністратора',
        validators=[Optional(), Length(max=2000)],
    )

    def validate_birth_date(self, field):
        if field.data is None:
            return
        if field.data > date.today():
            raise ValidationError('Дата народження не може бути в майбутньому')
        if field.data.year < 1900:
            raise ValidationError('Некоректний рік народження')
