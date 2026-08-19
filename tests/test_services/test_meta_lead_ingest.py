"""Тести розбору заявки Meta Lead Ads і прив'язки її до контакту.

Це критерії приймання N3, N4 і N5 плану (`docs/plan-meta-lead-ads.md`), і
перевіряють вони не «чи розібрався JSON», а чи не зшили ми картку з чужою
людиною. Тому майже кожен тест закінчується твердженням про КОНКРЕТНИЙ
контакт, а не про кількість рядків.

Мережі тут немає: `ingest_lead` бере вже готову відповідь Graph API, а
будівники payload-ів лежать у `tests/support/fake_meta_graph.py` -- копія
формату `field_data` у кожному тесті розійшлася б із реальністю на першій
же правці.
"""
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.medical_profile import MedicalProfile
from app.models.meta_lead import MetaLead, MetaLeadEvent
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import meta_lead_ingest as ingest
from app.services.participant_service import is_placeholder_email
from tests.support.fake_meta_graph import make_field_data, make_lead


# --- фікстури-помічники ---------------------------------------------------

def _phone():
    """Унікальний український номер на кожен тест.

    Константа тут не годиться: у наборі є тести, що комітять контакти повз
    відкат фікстури, і фіксований номер зіставився б із чужим лишком. Падало
    б це лише в ПОВНОМУ прогоні й виглядало б як дефект розбору.
    """
    return f'+38067{random.randrange(10 ** 7):07d}'


def _formats(phone):
    """Той самий номер усіма формами, якими його пишуть люди й Meta."""
    local = '0' + phone[4:]
    return [
        phone,                                       # +380671234567
        phone[1:],                                   # 380671234567
        local,                                       # 0671234567
        f'{local[:3]} {local[3:6]} {local[6:8]} {local[8:]}',
        f'({local[:3]}) {local[3:6]}-{local[6:8]}-{local[8:]}',
    ]


def _email(tag):
    """Унікальна адреса -- з тієї ж причини, що й унікальний номер."""
    return f'{tag}-{uuid4().hex[:10]}@example.com'


def _contact(email=None, phone=None, created_at=None, **profile_fields):
    """Наявна картка: User + MedicalProfile (як її створює адмінка/імпорт)."""
    user = User(email=email or _email('contact'))
    if created_at is not None:
        user.created_at = created_at
    db.session.add(user)
    db.session.flush()
    profile = MedicalProfile(user_id=user.id, source=MedicalProfile.SOURCE_IMPORTED)
    for attr, value in profile_fields.items():
        setattr(profile, attr, value)
    if phone:
        profile.phone = phone
    db.session.add(profile)
    user.medical_profile = profile
    db.session.flush()
    return user


def _lead(leadgen_id=None, **answers):
    """Відповідь Graph API із заданими відповідями форми."""
    return make_lead(
        leadgen_id=leadgen_id or uuid4().int % 10 ** 15,
        field_data=make_field_data(**answers),
    )


# --- нормалізація ---------------------------------------------------------

def test_field_data_list_and_dict_give_same_result(app):
    """Graph віддає список {name, values}; звірка й ручний повтор -- dict."""
    as_list = ingest.normalize_field_data(
        make_field_data(email='A@Example.COM ', phone_number='067 123 45 67'))
    as_dict = ingest.normalize_field_data(
        {'email': 'A@Example.COM ', 'phone_number': '067 123 45 67'})
    assert as_list == as_dict
    assert as_list.email == 'a@example.com'
    assert as_list.phone_e164 == '+380671234567'
    assert as_list.phone_raw == '067 123 45 67'


def test_full_name_and_split_names_give_same_result(app):
    """Форма з одним полем ПІБ і форма з двома мусять дати той самий запис,
    інакше та сама людина з двох кампаній виглядатиме як двоє різних."""
    joined = ingest.normalize_field_data(make_field_data(full_name='ОЛЕНА КОВАЛЬЧУК'))
    split = ingest.normalize_field_data(
        make_field_data(first_name='олена', last_name='ковальчук'))
    assert joined == split
    assert (joined.first_name, joined.last_name) == ('Олена', 'Ковальчук')
    assert joined.full_name == 'Олена Ковальчук'


def test_full_name_splits_on_first_space(app):
    parsed = ingest.normalize_field_data(
        make_field_data(full_name='Олена Марія Ковальчук'))
    assert parsed.first_name == 'Олена'
    assert parsed.last_name == 'Марія Ковальчук'


def test_foreign_phone_has_no_canonical_form(app):
    """Нормалізатор лише український: вигадана канонічна форма зшила б
    картку з ким завгодно (див. MedicalProfile._sync_phone_e164)."""
    parsed = ingest.normalize_field_data(make_field_data(phone_number='+1 415 555 0132'))
    assert parsed.phone_e164 is None
    assert parsed.phone_raw == '+1 415 555 0132'
    assert parsed.has_contacts is True


def test_custom_answers_go_to_custom(app):
    parsed = ingest.normalize_field_data(make_field_data(
        email='x@example.com',
        job_title='Дерматолог',
        company_name='Клініка Альфа',
        **{'Ваше місто?': 'Київ'},
    ))
    assert parsed.custom['Ваше місто?'] == 'Київ'
    # Стандартні поля Meta без колонки в ParsedLead лежать у custom під
    # канонічними ключами -- саме звідти їх читає apply_lead_to_contact.
    assert parsed.custom['job_title'] == 'Дерматолог'
    assert parsed.custom['company_name'] == 'Клініка Альфа'


def test_multiselect_values_are_joined(app):
    parsed = ingest.normalize_field_data(
        [{'name': 'Що цікавить?', 'values': ['PRP', 'Мезотерапія']}])
    assert parsed.custom['Що цікавить?'] == 'PRP, Мезотерапія'


# --- критерій N3: телефон у будь-якому форматі -> той самий контакт -------

#: Підписи форм запису номера -- лише для читабельних id параметризації.
_FORMAT_IDS = ['+380...', '380...', '0...', 'з пробілами', 'у дужках']


@pytest.mark.parametrize('form_index', range(len(_FORMAT_IDS)), ids=_FORMAT_IDS)
def test_any_phone_format_matches_same_contact(app, form_index):
    phone = _phone()
    contact = _contact(phone=phone)
    written = _formats(phone)[form_index]

    lead = ingest.ingest_lead(_lead(phone_number=written, full_name='Олена Ковальчук'))
    db.session.flush()

    assert lead.user_id == contact.id
    assert lead.match_method == MetaLead.MATCH_PHONE
    assert lead.phone_e164 == phone
    assert lead.phone_raw == written
    assert lead.needs_attention is False


def test_all_phone_formats_land_on_one_contact(app):
    """Той самий критерій, але в один прогін: п'ять заявок -- одна картка."""
    phone = _phone()
    contact = _contact(phone=phone)
    before = User.query.count()

    leads = [ingest.ingest_lead(_lead(phone_number=f)) for f in _formats(phone)]
    db.session.flush()

    assert {lead.user_id for lead in leads} == {contact.id}
    assert User.query.count() == before


# --- критерій N4: невідомий номер -> новий контакт ------------------------

def test_unknown_phone_creates_contact_with_fields(app):
    phone = _phone()
    email = _email('olena')
    before = User.query.count()

    lead = ingest.ingest_lead(_lead(
        full_name='Олена Ковальчук',
        email=email,
        phone_number=_formats(phone)[3],
        job_title='Дерматолог',
        company_name='Клініка Альфа',
    ))
    db.session.flush()

    assert User.query.count() == before + 1
    assert lead.match_method == MetaLead.MATCH_CREATED
    user = db.session.get(User, lead.user_id)
    assert (user.first_name, user.last_name) == ('Олена', 'Ковальчук')
    assert user.email == email

    profile = user.medical_profile
    assert profile.source == MedicalProfile.SOURCE_META
    assert profile.phone_e164 == phone
    assert profile.position == 'Дерматолог'
    assert profile.workplace == 'Клініка Альфа'
    assert lead.needs_attention is False


def test_lead_without_email_gets_placeholder(app):
    phone = _phone()
    lead = ingest.ingest_lead(_lead(full_name='Олена Ковальчук', phone_number=phone))
    db.session.flush()

    user = db.session.get(User, lead.user_id)
    assert is_placeholder_email(user.email) is True
    assert user.email.startswith(phone[1:])
    assert lead.email is None


def test_foreign_phone_matches_by_email_only(app):
    """Номер не розпізнано -> зіставлення лише за поштою."""
    email = _email('foreign')
    contact = _contact(email=email)

    lead = ingest.ingest_lead(_lead(email=email, phone_number='+1 415 555 0132'))
    db.session.flush()

    assert lead.user_id == contact.id
    assert lead.match_method == MetaLead.MATCH_EMAIL
    assert lead.phone_e164 is None
    assert lead.phone_raw == '+1 415 555 0132'
    # Сирий номер усе одно доїхав у картку -- менеджеру треба передзвонити.
    assert contact.medical_profile.phone == '+1 415 555 0132'
    assert contact.medical_profile.phone_e164 is None


def test_lead_without_any_contacts_creates_no_user(app):
    before = User.query.count()
    lead = ingest.ingest_lead(_lead(**{'Ваше місто?': 'Київ'}))
    db.session.flush()

    assert User.query.count() == before
    assert lead.user_id is None
    assert lead.match_method == MetaLead.MATCH_NONE
    assert lead.needs_attention is True


# --- критерій N5: конфлікт телефон/пошта ----------------------------------

def test_phone_email_conflict_binds_to_phone_without_merge(app):
    phone = _phone()
    phone_owner_email, mail_owner_email = _email('phone-owner'), _email('mail-owner')
    by_phone = _contact(email=phone_owner_email, phone=phone)
    by_email = _contact(email=mail_owner_email)
    before = User.query.count()

    lead = ingest.ingest_lead(_lead(
        phone_number=phone, email=mail_owner_email, full_name='Олена Ковальчук'))
    db.session.flush()

    assert lead.user_id == by_phone.id
    assert lead.conflict_user_id == by_email.id
    assert lead.match_method == MetaLead.MATCH_PHONE
    assert lead.needs_attention is True
    assert lead.attention_reason

    # Жодного злиття: обидві картки на місці, логіни не змінились.
    assert User.query.count() == before
    assert db.session.get(User, by_phone.id).email == phone_owner_email
    assert db.session.get(User, by_email.id).email == mail_owner_email
    # Нова адреса лежить окремо -- users.email це логін і унікальний ключ.
    assert lead.alt_email == mail_owner_email


def test_new_email_on_phone_match_goes_to_alt_email(app):
    phone = _phone()
    old_email, new_email = _email('old'), _email('brand-new')
    contact = _contact(email=old_email, phone=phone)

    lead = ingest.ingest_lead(_lead(phone_number=phone, email=new_email))
    db.session.flush()

    assert lead.user_id == contact.id
    assert lead.alt_email == new_email
    assert lead.needs_attention is True
    assert db.session.get(User, contact.id).email == old_email


def test_same_phone_on_two_contacts_picks_oldest(app):
    """Телефон у базі НЕ unique: клініка з єдиним номером -- звичайна річ."""
    phone = _phone()
    now = datetime.now(timezone.utc)
    older = _contact(phone=phone, created_at=now - timedelta(days=800))
    newer = _contact(phone=phone, created_at=now - timedelta(days=10))

    match = ingest.resolve_contact(None, phone)
    assert match.user.id == older.id
    assert match.extra_user_ids == [newer.id]
    assert match.needs_attention is True
    assert str(newer.id) in match.reason

    lead = ingest.ingest_lead(_lead(phone_number=phone))
    db.session.flush()
    assert lead.user_id == older.id
    assert lead.needs_attention is True


# --- оновлення контакту ---------------------------------------------------

def test_empty_fields_filled_filled_ones_kept(app):
    phone = _phone()
    contact = _contact(
        email=_email('kept'), phone=phone,
        position='Хірург', middle_name='Петрович',
    )
    contact.first_name = 'Іван'
    db.session.flush()

    ingest.ingest_lead(_lead(
        phone_number=phone, full_name='Олена Ковальчук',
        job_title='Дерматолог', company_name='Клініка Альфа',
    ))
    db.session.flush()

    user = db.session.get(User, contact.id)
    assert user.first_name == 'Іван'            # було заповнене -- не чіпаємо
    assert user.last_name == 'Ковальчук'        # було порожнє -- дописали
    assert user.medical_profile.position == 'Хірург'
    assert user.medical_profile.workplace == 'Клініка Альфа'
    assert user.medical_profile.middle_name == 'Петрович'


def test_existing_phone_is_not_overwritten(app):
    phone, email = _phone(), _email('same')
    contact = _contact(phone=phone, email=email)

    ingest.ingest_lead(_lead(email=email, phone_number='+1 415 555 0132'))
    db.session.flush()

    assert contact.medical_profile.phone == phone
    assert contact.medical_profile.phone_e164 == phone


def test_apply_lead_to_contact_creates_profile_with_meta_source(app):
    phone = _phone()
    user = User(email=_email('no-profile'))
    db.session.add(user)
    db.session.flush()

    parsed = ingest.normalize_field_data(
        make_field_data(full_name='Олена Ковальчук', phone_number=phone))
    ingest.apply_lead_to_contact(user, parsed)
    db.session.flush()

    assert user.medical_profile.source == MedicalProfile.SOURCE_META
    assert user.medical_profile.phone_e164 == phone


# --- повтор і ідемпотентність ---------------------------------------------

def test_second_lead_from_same_person_is_repeat(app):
    phone = _phone()
    contact = _contact(phone=phone)
    before = User.query.count()

    first = ingest.ingest_lead(_lead(phone_number=phone))
    db.session.flush()
    second = ingest.ingest_lead(_lead(phone_number=phone))
    db.session.flush()

    assert first.is_repeat is False
    assert second.is_repeat is True
    assert second.user_id == contact.id
    assert User.query.count() == before


def test_same_leadgen_id_twice_gives_one_lead(app):
    raw = _lead(phone_number=_phone())
    first = ingest.ingest_lead(raw)
    db.session.flush()
    second = ingest.ingest_lead(raw)
    db.session.flush()

    assert second.id == first.id
    assert MetaLead.query.filter_by(leadgen_id=raw['id']).count() == 1


def test_repeated_ingest_does_not_touch_existing_lead(app):
    raw = _lead(phone_number=_phone())
    lead = ingest.ingest_lead(raw)
    db.session.flush()
    lead.status = MetaLead.STATUS_IN_WORK
    lead.admin_notes = 'передзвонили'
    db.session.flush()

    again = ingest.ingest_lead(raw)
    assert again.status == MetaLead.STATUS_IN_WORK
    assert again.admin_notes == 'передзвонили'


def test_lead_without_leadgen_id_raises(app):
    with pytest.raises(ingest.MetaIngestError):
        ingest.ingest_lead({'field_data': make_field_data(email=_email('x'))})


# --- тестові заявки -------------------------------------------------------

def test_test_mode_marks_lead_as_test(app):
    # Свідомо не через SiteSettings.get(): на порожньому рядку він робить
    # commit, а в цьому наборі БД спільна на всю сесію -- зайвий commit
    # лишає сміття наступним файлам і робить їх нестабільними.
    settings = db.session.get(SiteSettings, 1)
    if settings is None:
        settings = SiteSettings(id=1)
        db.session.add(settings)
        db.session.flush()
    settings.meta_test_mode = True
    settings.meta_test_mode_since = datetime.now(timezone.utc)
    db.session.flush()
    try:
        lead = ingest.ingest_lead(
            _lead(phone_number=_phone(), full_name='Олена Ковальчук'))
        db.session.flush()
        assert lead.is_test is True
    finally:
        settings.meta_test_mode = False
        db.session.flush()


def test_normal_lead_is_not_test(app):
    lead = ingest.ingest_lead(_lead(phone_number=_phone(), full_name='Олена Ковальчук'))
    db.session.flush()
    assert lead.is_test is False


def test_testing_tool_name_is_detected(app):
    lead = ingest.ingest_lead(_lead(full_name='Test Lead', email=_email('t')))
    db.session.flush()
    assert lead.is_test is True


# --- джерело заявки -------------------------------------------------------

def test_source_fields_are_stored(app):
    leadgen_id = str(uuid4().int % 10 ** 15)
    raw = make_lead(leadgen_id=leadgen_id)
    event = MetaLeadEvent(
        leadgen_id=leadgen_id, page_id='555000111',
        raw_payload={'leadgen_id': leadgen_id, 'page_id': '555000111'},
        source=MetaLeadEvent.SOURCE_WEBHOOK,
    )
    db.session.add(event)
    db.session.flush()

    lead = ingest.ingest_lead(raw, event=event)
    db.session.flush()

    assert lead.form_id == '9988776655'
    assert lead.campaign_id == '23851234567890123'
    assert lead.campaign_name == 'PRP серпень'
    assert lead.adset_id == '23851234567890555'
    assert lead.ad_id == '23851234567890999'
    assert lead.platform == 'ig'
    assert lead.is_organic is False
    # page_id у відповіді GET /{leadgen_id} немає -- лише у вебхуці.
    assert lead.page_id == '555000111'
    assert lead.created_time.year == 2026
    assert lead.field_data['email'] == 'olena@example.com'
    assert lead.raw_lead['id'] == leadgen_id
    # Стан події ставить черга, не розбір.
    assert event.lead_id is None
    assert event.status == MetaLeadEvent.STATUS_PENDING


def test_created_time_accepts_unix_seconds(app):
    raw = _lead(phone_number=_phone())
    raw['created_time'] = 1755511452
    lead = ingest.ingest_lead(raw)
    db.session.flush()
    assert lead.created_time.tzinfo is not None
    assert lead.created_time.year == 2025


# --- гонка двох воркерів --------------------------------------------------

def test_parallel_delivery_returns_existing_lead(app, monkeypatch):
    """Дві доставки того самого ліда в різних воркерах: пре-перевірка їх не
    розводить (обидві бачать порожньо), розводить UNIQUE. Друга мусить
    повернути наявний лід, а не впасти й не лишити в сесії свій INSERT --
    інакше впав би commit викликача, уже поза нашим контролем."""
    raw = _lead(phone_number=_phone())
    first = ingest.ingest_lead(raw)
    db.session.flush()

    real = ingest._find_lead
    calls = {'n': 0}

    def blind_first_call(leadgen_id):
        calls['n'] += 1
        return None if calls['n'] == 1 else real(leadgen_id)

    monkeypatch.setattr(ingest, '_find_lead', blind_first_call)

    second = ingest.ingest_lead(raw)
    assert second.id == first.id
    # Сесія лишилась придатною: commit викликача проходить.
    db.session.flush()
    assert MetaLead.query.filter_by(leadgen_id=raw['id']).count() == 1
