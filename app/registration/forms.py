from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField
from wtforms.validators import (
    DataRequired, Length, Email, ValidationError,
)

from app.forms_medical import MedicalProfileFieldsMixin
from app.utils import UA_PHONE_RE, normalize_phone


class EventRegistrationForm(FlaskForm):
    """Реєстрація на CourseInstance -- ЛИШЕ базова інформація.

    Медична анкета (МОЗ України №725 п.13: тип учасника, дата народження,
    освіта, спеціалізації тощо) винесена ЗА рамки flow оплати -- учасник
    заповнює її в особистому кабінеті (auth.certificate_data), це умова
    отримання сертифіката, а не реєстрації. Рішення 08.07.2026.
    """
    # ----- ПІБ -----
    # last_name + first_name беруться з User (signup), але показуємо їх на
    # формі для редагування. Якщо змінились -- оновимо User у роуті.
    last_name = StringField(
        _l('Прізвище'),
        validators=[DataRequired(message=_l('Прізвище обов\'язкове')), Length(max=100)],
        render_kw={'autocomplete': 'family-name'},
    )
    first_name = StringField(
        _l('Ім\'я'),
        validators=[DataRequired(message=_l('Ім\'я обов\'язкове')), Length(max=100)],
        render_kw={'autocomplete': 'given-name'},
    )

    # ----- Контакт -----
    phone = StringField(
        _l('Телефон'),
        validators=[DataRequired(message=_l('Телефон обов\'язковий')), Length(max=20)],
        render_kw={'placeholder': '+380XXXXXXXXX', 'autocomplete': 'tel'},
    )

    def validate_phone(self, field):
        """Нормалізуємо до +380XXXXXXXXX (приймаємо 0XX/380/пробіли/дужки)
        і відхиляємо все, що не є валідним українським мобільним."""
        normalized = normalize_phone(field.data)
        if not normalized or not UA_PHONE_RE.match(normalized):
            raise ValidationError(
                _('Вкажіть коректний український номер у форматі +380XXXXXXXXX')
            )
        field.data = normalized

    # Спосіб оплати тут НЕ збираємо: для платних подій є окремий крок оплати
    # (confirmation.html / _pay_options), де користувач обирає LiqPay або
    # рахунок безпосередньо дією. reg.payment_method дефолтиться у 'liqpay' і
    # уточнюється фактом завантаження рахунка.

    # ----- Згоди (GDPR) -----
    consent_data = BooleanField(
        validators=[DataRequired(message=_l('Необхідно надати згоду на обробку персональних даних'))],
    )
    consent_marketing = BooleanField()


class ParticipantCompletionForm(MedicalProfileFieldsMixin, FlaskForm):
    """Публічна форма самостійного завершення реєстрації за токеном.

    Учасник заповнює анкету повністю -- УСІ поля обов'язкові (на відміну від
    admin-форми, де частина опціональна). МОЗ-поля -- з
    MedicalProfileFieldsMixin (спільні з анкетою в кабінеті).
    Реєстраційні/адмін-поля (статус, оплата, бали) сюди не виносяться --
    ними керує менеджер."""
    last_name = StringField(
        _l('Прізвище'),
        validators=[DataRequired(message=_l('Прізвище обов\'язкове')), Length(max=100)],
        render_kw={'autocomplete': 'family-name'},
    )
    first_name = StringField(
        _l('Ім\'я'),
        validators=[DataRequired(message=_l('Ім\'я обов\'язкове')), Length(max=100)],
        render_kw={'autocomplete': 'given-name'},
    )
    email = StringField(
        'Email',
        validators=[
            DataRequired(message=_l('Email обов\'язковий')),
            Email(message=_l('Невалідний email')),
            Length(max=255),
        ],
        render_kw={'autocomplete': 'email'},
    )
    phone = StringField(
        _l('Телефон'),
        validators=[DataRequired(message=_l('Телефон обов\'язковий')), Length(max=20)],
        render_kw={'placeholder': '+380XXXXXXXXX', 'autocomplete': 'tel'},
    )
    consent_data = BooleanField(
        validators=[DataRequired(message=_l('Необхідно надати згоду на обробку персональних даних'))],
    )
