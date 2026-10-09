"""Анкета кандидата в тренери (/trainers/join).

Поля питань про плазму будуються з app/data/trainer_application_questions:
префікс q_ + key. Вибір перевіряється проти переліку варіантів (WTForms
RadioField відкидає значення поза choices), тож підроблений POST нічого не
збереже.
"""
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, RadioField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, InputRequired, Length, Optional

from app.data.trainer_application_questions import QUESTIONS
from app.utils import normalize_whitespace

# Власні повідомлення, а не дефолт WTForms: той англійською ("This field is
# required.") і без перекладу показувався б на українській сторінці.
_REQUIRED = _l("Це поле обов'язкове")
_CHOOSE = _l('Оберіть один із варіантів')


class _BaseTrainerApplicationForm(FlaskForm):
    # filters -- до валідації: ПІБ іде в тему листа команді (Subject), а
    # перенос рядка там -- вставка нового заголовка, не просто вигляд.
    full_name = StringField(_l('ПІБ'), filters=[normalize_whitespace],
                            validators=[DataRequired(message=_REQUIRED), Length(max=200)])
    phone = StringField(_l('Телефон'), validators=[DataRequired(message=_REQUIRED), Length(max=20)])
    email = StringField(_l('Email'), validators=[
        DataRequired(message=_REQUIRED), Email(message=_l('Вкажіть валідний email')),
        Length(max=254)])
    city = StringField(_l('Місто'), validators=[Optional(), Length(max=120)])
    specialty = StringField(_l('Спеціальність'),
                            validators=[DataRequired(message=_REQUIRED), Length(max=255)])
    workplace = TextAreaField(_l('Місце роботи та посада'),
                              validators=[Optional(), Length(max=2000)])
    social_links = TextAreaField(_l('Соцмережі або сайт'),
                                 validators=[Optional(), Length(max=2000)])
    topic = TextAreaField(_l('Тема або напрям, з яким готові вийти до колег'),
                          validators=[DataRequired(message=_REQUIRED), Length(max=4000)])
    consent = BooleanField(_l('Погоджуюсь на обробку персональних даних'), validators=[
        DataRequired(message=_l('Необхідно надати згоду на обробку персональних даних'))])
    # Honeypot: справжня людина поле не бачить і не заповнює.
    website = StringField()


def _question_field(question):
    label = _l(question['label'])
    if question['kind'] == 'choice':
        return RadioField(label, choices=[(code, _l(text)) for code, text in question['options']],
                          validators=[InputRequired(message=_CHOOSE)])
    return TextAreaField(label, validators=[Optional(), Length(max=2000)])


TrainerApplicationForm = type(
    'TrainerApplicationForm',
    (_BaseTrainerApplicationForm,),
    {f"q_{q['key']}": _question_field(q) for q in QUESTIONS},
)
