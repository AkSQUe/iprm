"""MedicalProfile.is_complete -- критерій допуску до тестування й сертифіката.

Критерій посилено 17.08.2026: раніше він не вимагав `middle_name`, `workplace` і
`position`, хоч форма анкети позначає їх обов'язковими. Наслідок був відчутний:
профіль, створений адмінкою або xlsx-імпортом, вважався повним без місця роботи,
а `middle_name` ще й друкується у ПІБ на сертифікаті -- тобто документ виходив
дефектним. На проді таких «повних без по батькові» було 3 з 8.

Одне визначення на всі гейти навмисно: друге, «суворіше для сертифіката»,
розійшлося б із цим на першій же правці.
"""
from datetime import date
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.medical_profile import MedicalProfile
from app.models.user import User


FULL = {
    'participant_type': 'doctor',
    'middle_name': 'Іванович',
    'birth_date': date(1985, 3, 12),
    'education': '2010, НМУ ім. О.О. Богомольця',
    'workplace': 'Клініка №1',
    'position': 'лікар-ординатор',
    'specializations': ['therapy'],
}


def _profile(**overrides):
    user = User.create_with_password(
        f'mp-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Іван', last_name='Іванов', email_confirmed=True)
    db.session.flush()
    profile = user.medical_profile or MedicalProfile(user_id=user.id)
    for field, value in {**FULL, **overrides}.items():
        setattr(profile, field, value)
    user.medical_profile = profile
    db.session.add(profile)
    db.session.flush()
    return profile


def test_full_profile_is_complete(app):
    assert _profile().is_complete is True


@pytest.mark.parametrize('field', [
    'participant_type', 'middle_name', 'birth_date',
    'education', 'workplace', 'position',
])
def test_any_missing_required_field_breaks_completeness(app, field):
    assert _profile(**{field: None}).is_complete is False


@pytest.mark.parametrize('value', [None, []])
def test_specializations_must_be_non_empty(app, value):
    assert _profile(specializations=value).is_complete is False


def test_middle_name_is_now_required(app):
    """Головний регрес: саме воно друкується у ПІБ на сертифікаті."""
    assert _profile(middle_name=None).is_complete is False


def test_workplace_is_now_required(app):
    """Профілі з xlsx-імпорту раніше проходили без місця роботи."""
    assert _profile(workplace=None).is_complete is False


def test_empty_string_counts_as_missing(app):
    assert _profile(workplace='').is_complete is False


# --- перелік того, чого бракує -----------------------------------------------

def test_missing_fields_empty_for_full_profile(app):
    assert _profile().missing_fields == []


def test_missing_fields_names_the_gaps(app):
    """Гейт мусить казати, ЧОГО бракує: після посилення критерію людині з
    давнім профілем інакше незрозуміло, що робити."""
    profile = _profile(middle_name=None, workplace=None, specializations=[])
    assert profile.missing_fields == [
        'По батькові', 'Місце роботи', 'Спеціалізації',
    ]


def test_missing_fields_order_follows_form(app):
    profile = _profile(
        participant_type=None, middle_name=None, birth_date=None,
        education=None, workplace=None, position=None, specializations=[],
    )
    assert profile.missing_fields == [
        'Тип учасника', 'По батькові', 'Дата народження', 'Освіта',
        'Місце роботи', 'Займана посада', 'Спеціалізації',
    ]


# --- узгодженість із формою --------------------------------------------------

def test_criterion_matches_required_form_fields(app):
    """Розходження форми й критерію -- саме те, що ми щойно прибрали.

    Якщо у форму додадуть ще одне обов'язкове поле, а в `is_complete` ні (або
    навпаки), цей тест впаде -- і розбіжність не проживе до прода.
    """
    from wtforms.fields.core import UnboundField
    from wtforms.validators import DataRequired, InputRequired

    from app.forms_medical import MedicalProfileFieldsMixin

    required = set()
    for name in dir(MedicalProfileFieldsMixin):
        field = getattr(MedicalProfileFieldsMixin, name, None)
        if not isinstance(field, UnboundField):
            continue
        validators = field.kwargs.get('validators') or []
        if any(isinstance(v, (DataRequired, InputRequired)) for v in validators):
            required.add(name)

    # `user_type` у формі == `participant_type` у моделі (історична назва поля).
    expected = {
        'user_type', 'middle_name', 'birth_date', 'education',
        'workplace', 'position', 'specializations',
    }
    assert required == expected, (
        'обов’язкові поля форми змінилися -- звірте MedicalProfile.is_complete '
        'і missing_fields'
    )
