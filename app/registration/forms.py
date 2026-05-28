from flask_wtf import FlaskForm
from wtforms import (
    StringField, IntegerField, BooleanField, DateField, SelectField,
    SelectMultipleField,
)
from wtforms.validators import DataRequired, Length, Optional, NumberRange

from app.models.medical_profile import MedicalProfile
from app.models.specializations import SPECIALIZATIONS


class EventRegistrationForm(FlaskForm):
    """Реєстрація на CourseInstance. Поля медичної анкети (МОЗ України
    №725 п.13) збираються тут і зберігаються у MedicalProfile користувача
    для пре-філу майбутніх реєстрацій.
    """
    # ----- Тип користувача (МОЗ) -----
    user_type = SelectField(
        'Тип учасника',
        choices=[('', '— оберіть —')] + MedicalProfile.PARTICIPANT_TYPES,
        validators=[DataRequired(message='Оберіть тип учасника')],
    )

    # ----- ПІБ -----
    # last_name + first_name беруться з User (signup), але показуємо їх на
    # формі для редагування. Якщо змінились -- оновимо User у роуті.
    last_name = StringField(
        'Прізвище',
        validators=[DataRequired(message='Прізвище обов\'язкове'), Length(max=100)],
        render_kw={'autocomplete': 'family-name'},
    )
    first_name = StringField(
        'Ім\'я',
        validators=[DataRequired(message='Ім\'я обов\'язкове'), Length(max=100)],
        render_kw={'autocomplete': 'given-name'},
    )
    middle_name = StringField(
        'По батькові',
        validators=[Optional(), Length(max=100)],
        render_kw={'autocomplete': 'additional-name'},
    )

    # ----- Контакт + дата народження -----
    phone = StringField(
        'Телефон',
        validators=[DataRequired(message='Телефон обов\'язковий'), Length(max=20)],
        render_kw={'placeholder': '+380XXXXXXXXX', 'autocomplete': 'tel'},
    )
    birth_date = DateField(
        'Дата народження',
        validators=[DataRequired(message='Дата народження обов\'язкова')],
        render_kw={'autocomplete': 'bday'},
    )

    # ----- Освіта і робота -----
    education = StringField(
        'Освіта (рік закінчення та назва ВНЗ)',
        validators=[
            DataRequired(message='Освіта обов\'язкова'),
            Length(max=500),
        ],
        render_kw={'placeholder': '2014, НМУ ім. О.О. Богомольця'},
    )
    workplace = StringField(
        'Місце роботи (назва ЗОЗу)',
        validators=[
            DataRequired(message='Місце роботи обов\'язкове'),
            Length(max=300),
        ],
        render_kw={'autocomplete': 'organization'},
    )
    position = StringField(
        'Займана посада',
        validators=[
            DataRequired(message='Займана посада обов\'язкова'),
            Length(max=200),
        ],
        render_kw={
            'placeholder': 'асистент, лікар-ординатор, головний лікар...',
            'autocomplete': 'organization-title',
        },
    )

    # ----- Спеціалізації (multi-select) -----
    # Choices з довідника. На рендері show'имо як список чекбоксів
    # (template), а не як <select multiple> -- так UX краще.
    specializations = SelectMultipleField(
        'Спеціалізації',
        choices=SPECIALIZATIONS,
        validators=[DataRequired(message='Оберіть хоча б одну спеціалізацію')],
    )

    # ----- Опціональне (історичне) -----
    experience_years = IntegerField(
        'Стаж роботи (років)',
        validators=[Optional(), NumberRange(min=0, max=70)],
        render_kw={'placeholder': '0'},
    )
    license_number = StringField(
        'Номер ліцензії',
        validators=[Optional(), Length(max=50)],
        render_kw={'placeholder': 'Номер ліцензії лікаря'},
    )

    # ----- Згоди (GDPR) -----
    consent_data = BooleanField(
        validators=[DataRequired(message='Необхідно надати згоду на обробку персональних даних')],
    )
    consent_marketing = BooleanField()
