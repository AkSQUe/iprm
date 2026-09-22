"""Форми анкети тренера: профіль і пропозиція курсу/доповіді."""
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, DateField, StringField, TextAreaField
from wtforms.validators import (
    DataRequired, Email, Length, Optional, ValidationError)

from app.forms_validators import HttpUrl
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.utils import normalize_whitespace


def _link_validators():
    return [Optional(), HttpUrl(_l('Невалідне посилання')), Length(max=500)]


class TrainerProfileForm(FlaskForm):
    # Контактна інформація
    full_name = StringField(_l('ПІБ'), validators=[Optional(), Length(max=200)])
    birth_date = DateField(_l('Дата народження'), validators=[Optional()])
    education = TextAreaField(_l('Освіта (рівень освіти та навчальні заклади)'), validators=[Optional()])
    position_titles = TextAreaField(_l('Посада та регалії'), validators=[Optional()])
    workplace = TextAreaField(_l('Місце роботи, місто'), validators=[Optional()])
    professional_certificates = TextAreaField(
        _l('Професійні сертифікати (по одному в рядку)'),
        validators=[Optional()])
    phone = StringField(_l('Телефон'), validators=[Optional(), Length(max=30)])
    email = StringField(_l('Ел. пошта'), validators=[
        Optional(), Email(message=_l('Невалідний email')), Length(max=255)])
    social_links = TextAreaField(_l('Посилання на соцмережі'), validators=[Optional()])
    photo = FileField(_l('Фотографія для сайту'), validators=[
        Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'webp', 'heic'],
                                _l('Дозволені формати: JPG, PNG, WebP, HEIC'))])
    photo_url = StringField(_l('Або посилання на фото (файлообмінник)'),
                            validators=_link_validators())
    # Завантажений файл має перевагу над посиланням (TrainerProfile.photo_src),
    # тож без явного прибирання перейти з файлу на посилання було неможливо.
    # Лише явна галочка: порожнє поле файлу в кожному сабміті -- норма, і
    # мовчки чистити фото за ним не можна.
    remove_photo = BooleanField(_l('Прибрати завантажене фото'))

    # Реквізити ФОП
    fop_recipient = StringField(_l('Отримувач'), validators=[Optional(), Length(max=300)])
    fop_iban = StringField('IBAN', validators=[Optional(), Length(max=34)])
    fop_rnokpp = StringField(_l('РНОКПП'), validators=[Optional(), Length(max=12)])
    fop_payment_purpose = TextAreaField(_l('Призначення платежу згідно ваших КВЕД'), validators=[Optional()])
    card_number = StringField(_l('Номер картки'), validators=[Optional(), Length(max=23)])

    # Дані для договору
    tax_id = StringField(_l('Ідентифікаційний код'), validators=[Optional(), Length(max=12)])
    registration_address = TextAreaField(_l('Адреса реєстрації (проживання)'), validators=[Optional()])
    edrpou = StringField(_l('ЄДРПОУ'), validators=[Optional(), Length(max=20)])

    # Поля, що копіюються в модель як є (фото обробляє маршрут окремо).
    MODEL_FIELDS = (
        'full_name', 'birth_date', 'education', 'position_titles', 'workplace',
        'professional_certificates',
        'phone', 'email', 'social_links', 'photo_url', 'fop_recipient', 'fop_iban',
        'fop_rnokpp', 'fop_payment_purpose', 'card_number', 'tax_id',
        'registration_address', 'edrpou',
    )


class ProposalForm(FlaskForm):
    # filters -- нормалізація ДО валідації: CR/LF з назви йде прямо в
    # заголовок листа куратору (Subject), а сирий перенос рядка там -- це
    # вставка нового заголовка, а не просто негарний вигляд.
    title = StringField(_l('Назва курсу/доповіді'), filters=[normalize_whitespace], validators=[
        DataRequired(message=_l("Назва обов'язкова")),
        Length(max=TrainerCourseProposal.TITLE_MAX,
               # Length() сам підставляє %(max)d зі свого значення max=:
               # текст і межа беруться з однієї константи, розсинхрон
               # неможливий за конструкцією.
               message=_l('Не більше %(max)d символів'))])
    theses = TextAreaField(_l('Програма виступу (5-10 головних тез)'))
    language = StringField(_l('Мова доповіді'), validators=[Optional(), Length(max=50)])
    relevance = TextAreaField(_l('Актуальність вебінару/лекції/курсу'), validators=[Optional()])
    target_specialties = TextAreaField(_l('Яким спеціальностям буде корисним'), validators=[Optional()])
    resources = TextAreaField(_l('Цікаві статті/ресурси по вашій темі'), validators=[Optional()])
    future_topics = TextAreaField(_l('Які теми в майбутньому ви могли б запропонувати'), validators=[Optional()])
    quiz_url = StringField(_l('Посилання на тестування (Google-форма)'),
                           validators=_link_validators())

    def theses_list(self):
        return [line.strip() for line in (self.theses.data or '').splitlines() if line.strip()]

    def validate_theses(self, field):
        items = self.theses_list()
        if not items:
            raise ValidationError(_l('Додайте хоча б одну тезу'))
        if len(items) > TrainerCourseProposal.THESES_MAX:
            raise ValidationError(
                _l('Не більше %(max)d тез', max=TrainerCourseProposal.THESES_MAX))


class MaterialRequestForm(FlaskForm):
    """Заявка на матеріали. Рядки приходять паралельними списками
    `sku[]`/`quantity[]`, тож полів під них тут немає -- WTForms не вміє
    динамічну кількість рядків без FieldList, а FieldList тут дав би
    складність без користі. Форма потрібна заради CSRF і коментаря.
    """
    comment = TextAreaField(_l('Коментар до заявки'), validators=[Optional()])
