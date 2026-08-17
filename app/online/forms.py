"""Форми публічного розділу онлайн-курсів."""
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField
from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError

from app.utils import UA_PHONE_RE, normalize_phone


class OnlineBuyerForm(FlaskForm):
    """Дані покупця для гостьової покупки онлайн-курсу.

    Набір полів мінімальний і продиктований тим, що з ними робиться далі:
    email -- канал доставки доступу й адреса учня в Sintegrum, ПІБ -- ім'я
    того ж учня в чужій системі. Медичної анкети тут немає взагалі: за
    онлайн-курс ІПРМ не видає сертифіката БПР, тож питати дату народження й
    спеціалізацію не було б за що.

    Телефон, на відміну від реєстрації на захід, НЕ обов'язковий: там він
    потрібен, щоб нагадати про дату й пояснити, як підключитись, а тут
    навчання починається з листа й дати не має.
    """
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
            DataRequired(message=_l('Email обовʼязковий')),
            Email(message=_l('Невалідний email')),
            Length(max=255),
        ],
        render_kw={'autocomplete': 'email', 'inputmode': 'email'},
    )
    phone = StringField(
        _l('Телефон'),
        validators=[Optional(), Length(max=20)],
        render_kw={'placeholder': '+380XXXXXXXXX', 'autocomplete': 'tel'},
    )

    consent_data = BooleanField(
        validators=[DataRequired(
            message=_l('Необхідно надати згоду на обробку персональних даних'))],
    )
    # Згоди на маркетинг тут свідомо НЕМАЄ. У формі заходу така галочка є,
    # але її значення нікуди не зберігається -- обіцянка "згоду можна
    # відкликати" не підкріплена нічим. Повторювати це в новій формі не
    # варто; з'явиться місце для зберігання -- з'явиться й поле.

    def validate_phone(self, field):
        """Нормалізуємо до +380XXXXXXXXX; порожнє поле пропускаємо.

        Правило те саме, що у формі реєстрації на захід -- номер потім
        лягає в той самий MedicalProfile.phone, і два різні уявлення про
        «коректний номер» розійшлися б на першому ж імпорті.
        """
        if not (field.data or '').strip():
            field.data = ''
            return
        normalized = normalize_phone(field.data)
        if not normalized or not UA_PHONE_RE.match(normalized):
            raise ValidationError(
                _l('Вкажіть коректний український номер у форматі +380XXXXXXXXX')
            )
        field.data = normalized
