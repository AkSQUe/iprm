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
from app.models.promo_code import PromoCode
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
    upcoming_events_style = SelectField(
        'Вигляд блоку «найближчі заходи»',
        choices=[('popup', 'Плаваючий блок (знизу зліва)'),
                 ('bar', 'Закріплена плашка (під шапкою)')],
        validators=[Optional()],
        description='Плашка показує події одним рядком на всю ширину і теж закривається відвідувачем.',
    )
    seats_low_threshold = IntegerField(
        'Поріг «мало місць»',
        default=5,
        validators=[InputRequired(message='Вкажіть поріг (0 вимикає підсвітку)'),
                    NumberRange(min=0, max=1000)],
        description='Коли вільних місць стільки або менше — лічильник підсвічується попередженням. 0 — підсвітку вимкнено.',
    )
    show_roi_calculator = BooleanField(
        'Показувати ROI-калькулятор окупності',
        description='Інтерактивний блок «Коли курс окупиться?» на сторінках платних курсів.',
    )
    show_home_hero_video = BooleanField(
        'Фонове відео у hero Головної',
        description='Приглушене відео за заголовком Головної. Вимкнено — hero повертається до світлого тла без відео й постера. Відео і так не вантажиться на мобільних, при економії трафіку та prefers-reduced-motion.',
    )
    certdata_reminder_days = IntegerField(
        'Нагадування про анкету, днів до заходу',
        default=3,
        validators=[InputRequired(message='Вкажіть кількість днів (0 вимикає)'),
                    NumberRange(min=0, max=60)],
        description='Авто-email «заповніть дані для сертифіката» учасникам з незаповненою МОЗ-анкетою, коли до заходу лишається стільки днів. 0 — вимкнено.',
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
    founding_year = IntegerField(
        'Рік заснування',
        validators=[Optional(), NumberRange(min=1900, max=2100)],
        default=2015,
        description='Використовується для лічильника «років досвіду» на Головній.',
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

    # Реферальна програма
    referral_enabled = BooleanField(
        'Увімкнути реферальну програму',
        default=False,
    )
    referral_points_per_paid = IntegerField(
        'Бонусних балів за оплачену реєстрацію',
        validators=[Optional(), NumberRange(min=0, max=100000)],
        default=1,
        description=(
            'Скільки бонусних балів лояльності нараховувати рефереру '
            '(учаснику/тренеру) за одну оплачену реєстрацію за його посиланням.'
        ),
    )
    referral_cookie_days = IntegerField(
        'Термін атрибуції (днів)',
        validators=[Optional(), NumberRange(min=1, max=3650)],
        default=60,
        description='Скільки днів тримається cookie "хто привів".',
    )
    referral_attribution = SelectField(
        'Модель атрибуції',
        choices=[('last', 'Останній клік (last-touch)'),
                 ('first', 'Перший клік (first-touch)')],
        default='last',
    )
    referral_maturity_days = IntegerField(
        'Період дозрівання балів (днів)',
        validators=[Optional(), NumberRange(min=0, max=365)],
        default=0,
        description=(
            'Бали лежать неактивними цю кількість днів (антифрод проти '
            'повернень). 0 -- активуються одразу.'
        ),
    )
    referral_max_per_referrer = IntegerField(
        'Стеля нарахувань на реферера',
        validators=[Optional(), NumberRange(min=0, max=1000000)],
        default=0,
        description='Максимум активних нарахувань на одного реферера. 0 -- без ліміту.',
    )
    referral_notify_referrer = BooleanField(
        'Слати рефереру лист про нарахування',
        default=True,
    )

    # Промокод-подяка (лист про оплату)
    thankyou_promo_enabled = BooleanField(
        'Видавати промокод на наступний курс після оплати',
        default=False,
    )
    # filters: колонки NOT NULL, а порожнє поле дає None -- без підстановки
    # дефолту збереження налаштувань падало б на порожньому вводі.
    thankyou_promo_percent = IntegerField(
        'Знижка промокоду (%)',
        validators=[Optional(), NumberRange(min=1, max=100)],
        default=10,
        filters=[lambda v: 10 if v in (None, '') else v],
        description=(
            'Персональний одноразовий код, який учасник отримує в листі '
            'про оплату. Діє на будь-який наступний курс.'
        ),
    )
    thankyou_promo_days = IntegerField(
        'Термін дії промокоду (днів)',
        validators=[Optional(), NumberRange(min=1, max=365)],
        default=30,
        filters=[lambda v: 30 if v in (None, '') else v],
        description='Дедлайн -- те, що змушує повернутись, а не відкласти.',
    )
    registration_email_delay_minutes = IntegerField(
        'Затримка листа про реєстрацію (хвилин)',
        validators=[Optional(), NumberRange(min=0, max=120)],
        default=5,
        filters=[lambda v: 5 if v in (None, '') else v],
        description=(
            'Пауза перед листом "Реєстрацію підтверджено" для неоплачених '
            'реєстрацій -- щоб платіж встиг дійти. Якщо за цей час оплата '
            'надійшла, лист не надсилається взагалі. 0 -- слати негайно.'
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
    difficulty_level = SelectField(
        'Рівень складності',
        coerce=int,
        choices=[(0, 'Не вказано')] + Course.DIFFICULTY_LEVELS,
        validators=[Optional()],
        description='Показується бейджем "Рівень N/3" на картці та сторінці курсу.',
    )
    roi_hint = StringField(
        'Орієнтир окупності',
        validators=[Optional(), Length(max=200)],
        description='Напр. "Окупність ≈ 3–4 записи за чека 6 000–9 000 грн". Показується на картці та в hero сторінки курсу.',
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
    final_cta_text = StringField(
        'Фінальний заклик',
        validators=[Optional(), Length(max=300)],
        description='Одне речення у блоці з кнопкою реєстрації внизу сторінки. '
                    'Порожньо -- показуємо стандартний текст.',
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
    is_pinned = BooleanField(
        'Закріпити вгорі каталогу',
        description='Закріплені курси показуються першими незалежно від порядку.',
    )
    sort_order = IntegerField(
        'Порядок у каталозі',
        default=0,
        validators=[Optional(), NumberRange(min=-1000, max=1000)],
        description='Менше число — вище в каталозі. Однаковий порядок сортується за назвою.',
    )


class InstanceTariffForm(FlaskForm):
    """Тариф (опція участі) проведення: назва, склад, ручна ціна."""
    name = StringField(
        'Назва тарифу',
        validators=[DataRequired(message='Назва обов\'язкова'), Length(max=100)],
        description='Напр. Онлайн, Онлайн+, Практикум, Практикум з менторством.',
    )
    price = DecimalField(
        'Ціна (UAH)',
        validators=[InputRequired(message='Вкажіть ціну'), NumberRange(min=0)],
    )
    description = TextAreaField(
        'Що входить',
        validators=[Optional()],
        description='Один пункт на рядок (лекція, запис, сертифікат, чат з тренером...).',
    )
    event_format = SelectField(
        'Формат участі',
        choices=[],  # заповнюється у роуті з InstanceTariff.FORMAT_CHOICES
        validators=[Optional()],
        description='Онлайн-тариф не просить підтверджувати приїзд на місце. '
                    'Не вказано -- вважається очною участю.',
    )
    sort_order = IntegerField(
        'Порядок',
        default=0,
        validators=[Optional(), NumberRange(min=-1000, max=1000)],
        description='Менше число — лівіше/вище. Рекомендовано: від економ до преміум.',
    )
    is_active = BooleanField('Активний (показується і доступний для вибору)', default=True)


class CourseTariffForm(FlaskForm):
    """Шаблонний тариф курсу (дефолтна вилка; копіюється у нові проведення)."""
    name = StringField(
        'Назва тарифу',
        validators=[DataRequired(message='Назва обов\'язкова'), Length(max=100)],
        description='Напр. Онлайн, Онлайн+, Практикум, Практикум з менторством.',
    )
    price = DecimalField(
        'Ціна за замовчуванням (UAH)',
        validators=[InputRequired(message='Вкажіть ціну'), NumberRange(min=0)],
        description='На конкретному проведенні ціну можна змінити після копіювання.',
    )
    description = TextAreaField(
        'Що входить',
        validators=[Optional()],
        description='Один пункт на рядок (лекція, запис, сертифікат, чат з тренером...).',
    )
    event_format = SelectField(
        'Формат проведення',
        choices=[('', 'Будь-який формат'),
                 ('online', 'Лише онлайн-проведення'),
                 ('offline', 'Лише офлайн-проведення')],
        validators=[Optional()],
        description='Онлайн-проведення отримає лише онлайн-шаблони; гібрид — усі.',
    )
    sort_order = IntegerField(
        'Порядок',
        default=0,
        validators=[Optional(), NumberRange(min=-1000, max=1000)],
        description='Менше число — вище. Рекомендовано: від економ до преміум.',
    )
    is_active = BooleanField('Активний (копіюється у нові проведення)', default=True)


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
        description='Адреса для людини: місто, вулиця, назва закладу',
    )
    city_id = SelectField(
        'Місто',
        coerce=int,
        validators=[Optional()],
        description='Окремо від адреси -- саме за ним працює фільтр розкладу, '
                    'зокрема на партнерських сайтах',
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


class ReviewForm(FlaskForm):
    """Відгук випускника (публічний блок "Після навчання" на Головній)."""
    author_name = StringField(
        'Ім\'я автора',
        validators=[DataRequired(message='Вкажіть ім\'я'), Length(max=120)],
    )
    author_role = StringField(
        'Роль / спеціальність',
        validators=[Optional(), Length(max=160)],
        description='Напр. "лікарка-косметологиня" або "власниця кабінету".',
    )
    city = StringField('Місто', validators=[Optional(), Length(max=120)])
    text = TextAreaField(
        'Текст відгуку',
        validators=[DataRequired(message='Текст обов\'язковий'), Length(max=2000)],
    )
    rating = SelectField(
        'Оцінка',
        choices=[(str(i), '%d ★' % i) for i in range(5, 0, -1)],
        default='5',
    )
    sort_order = IntegerField(
        'Порядок', validators=[Optional(), NumberRange(min=0)], default=0,
    )
    course_id = SelectField(
        'Курс (опційно)', choices=[], validators=[Optional()], coerce=str,
        description='Привʼязати відгук до курсу -- показати на його сторінці.',
    )
    is_published = BooleanField('Опубліковано', default=False)


class PromoCodeForm(FlaskForm):
    """Промокод: знижка, ліміти, вікно дії та область застосування.

    Валідність самого коду (унікальність) перевіряє роут -- форма не має
    доступу до того, який саме код зараз редагується.
    """
    code = StringField(
        'Промокод',
        validators=[DataRequired(message='Код обов\'язковий'), Length(max=64)],
        description='Те, що людина введе на формі реєстрації. Регістр і '
                    'пробіли не мають значення: «Дмитро» = «дмитро».',
        render_kw={'autocomplete': 'off', 'placeholder': 'Наприклад: Дмитро'},
    )
    description = StringField(
        'Для кого / навіщо',
        validators=[Optional(), Length(max=255)],
        description='Підказка собі: партнер, клініка, тест механіки.',
    )
    discount_type = SelectField(
        'Тип знижки',
        choices=PromoCode.DISCOUNT_TYPES,
        default='percent',
    )
    discount_value = DecimalField(
        'Розмір знижки',
        validators=[InputRequired(message='Вкажіть розмір знижки'),
                    NumberRange(min=0.01)],
        description='Для відсотка -- від 1 до 100 (100 = безкоштовно). '
                    'Для суми -- гривні; більша за ціну знижка просто '
                    'обнуляє рахунок.',
    )
    max_uses = IntegerField(
        'Ліміт застосувань',
        validators=[Optional(), NumberRange(min=1)],
        description='Скільки разів кодом можна скористатись загалом. '
                    'Порожнє -- без обмежень.',
    )
    per_user_limit = IntegerField(
        'Ліміт на одну людину',
        default=1,
        validators=[Optional(), NumberRange(min=1)],
        description='Порожнє -- без обмежень (людина зможе застосувати код '
                    'на кількох заходах).',
    )
    valid_from = DateTimeLocalField(
        'Діє з', format='%Y-%m-%dT%H:%M', validators=[Optional()],
        description='Порожнє -- діє одразу.',
    )
    valid_until = DateTimeLocalField(
        'Діє до', format='%Y-%m-%dT%H:%M', validators=[Optional()],
        description='Порожнє -- безстроково.',
    )
    course_id = SelectField(
        'Лише для курсу', choices=[], validators=[Optional()], coerce=str,
        description='Код працюватиме на всіх проведеннях цього курсу.',
    )
    instance_id = SelectField(
        'Лише для проведення', choices=[], validators=[Optional()], coerce=str,
        description='Найвужча прив\'язка -- одна конкретна дата. Має '
                    'пріоритет над курсом.',
    )
    is_active = BooleanField('Активний', default=True)
    batch_count = IntegerField(
        'Скільки кодів створити',
        default=1,
        validators=[Optional(), NumberRange(min=1, max=200)],
        description='Більше одного -- поле «Промокод» стає префіксом, і кожен '
                    'код отримає власний суфікс (напр. PHARMA-A7K3XY). '
                    'Зручно, коли партнер роздає коди різним людям.',
    )

    def validate_discount_value(self, field):
        if (self.discount_type.data == 'percent'
                and field.data is not None and field.data > 100):
            raise ValidationError('Відсоткова знижка не може перевищувати 100%')

    def validate_valid_until(self, field):
        if (field.data and self.valid_from.data
                and field.data <= self.valid_from.data):
            raise ValidationError('«Діє до» має бути пізніше за «Діє з»')


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
        description='Сума ДО знижки. Якщо нижче вказано промокод, підсумок '
                    'перерахується автоматично.',
    )
    promo_code = StringField(
        'Промокод',
        validators=[Optional(), Length(max=64)],
        description='Застосувати знижку до цієї реєстрації. Порожнє поле '
                    'знімає раніше застосований код і повертає його ліміт.',
        render_kw={'autocomplete': 'off'},
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
