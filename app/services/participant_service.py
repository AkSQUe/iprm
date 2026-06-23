"""Канонічна логіка створення/оновлення учасника заходу.

Один учасник = User (identity) + MedicalProfile (медичні дані) +
EventRegistration (реєстрація на CourseInstance). Цей сервіс -- єдине джерело
правди для upsert-у: його використовують і ручна admin-форма
(routes_participants), і xlsx-імпорт (xlsx_io). Усі функції мутують сесію
БЕЗ commit -- caller відповідає за commit/rollback (щоб xlsx міг застосувати
багато рядків атомарно).

Email не обов'язковий: якщо його немає, користувачу присвоюється
placeholder-email <цифри-телефону>@noemail.invalid ('.invalid' -- RFC 2606,
гарантовано недоставлюваний). Реальний email додається пізніше.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.specializations import labels_for_codes
from app.models.user import User
from app.services import registration_service

logger = logging.getLogger(__name__)

PLACEHOLDER_EMAIL_DOMAIN = 'noemail.invalid'
# 'xlsx.temp' -- спадок скрипта імпорту, теж вважаємо placeholder-ом.
_PLACEHOLDER_DOMAINS = {PLACEHOLDER_EMAIL_DOMAIN, 'xlsx.temp'}

# Події зберігаються в UTC; для ярликів показуємо київську дату (UTC+3).
_KYIV = timezone(timedelta(hours=3))

# Максимальна довжина snapshot-поля specialty (EventRegistration.specialty).
_SPECIALTY_MAX = 200


def event_label(instance, with_id=False, with_status=False):
    """Єдиний людиночитний ярлик CourseInstance для UI (форма + xlsx).

    with_id     -- префікс '#<id>' (потрібен xlsx для зворотного парсингу).
    with_status -- суфікс '(Статус)' (зручно у випадних списках форми).
    Дата -- київська (події в UTC), щоб уникнути зсуву на нічних подіях.
    """
    title = instance.course.title if instance.course else f'Захід #{instance.id}'
    sd = instance.start_date
    if sd is not None and sd.tzinfo is not None:
        sd = sd.astimezone(_KYIV)
    date_s = sd.strftime('%d.%m.%Y') if sd else 'без дати'
    core = f'{title} -- {date_s}'
    label = f'#{instance.id} -- {core}' if with_id else core
    if with_status:
        status = dict(CourseInstance.STATUSES).get(instance.status, instance.status)
        label += f' ({status})'
    return label


def _specialty_snapshot(labels_joined):
    """Обрізати specialty до ліміту БД, не ріжучи мітку посеред слова."""
    if len(labels_joined) <= _SPECIALTY_MAX:
        return labels_joined
    trimmed = labels_joined[:_SPECIALTY_MAX]
    cut = trimmed.rfind(', ')
    return trimmed[:cut] if cut > 0 else trimmed


class ParticipantError(Exception):
    """Доменна помилка операції над учасником (показується користувачу)."""


def _normalize_data(data):
    """Нормалізувати ПІБ і телефон у вхідному dict (форма + xlsx).

    Гарантує єдиний канонічний формат у БД незалежно від джерела:
    ПІБ -- кирилиця з великої літери, телефон -- +380XXXXXXXXX.
    """
    from app.utils import normalize_name, normalize_phone
    data = dict(data)
    for key in ('last_name', 'first_name', 'middle_name'):
        if key in data:
            data[key] = normalize_name(data.get(key))
    if data.get('phone'):
        data['phone'] = normalize_phone(data.get('phone'))
    return data


def _strip_or_none(value):
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _set_if(obj, attr, value):
    """Записати value у obj.attr лише якщо воно непорожнє -- не затираємо
    наявні дані порожнім вводом (важливо при reuse/редагуванні)."""
    if value not in (None, ''):
        setattr(obj, attr, value)


def is_placeholder_email(email):
    """True, якщо email -- згенерований placeholder, а не реальна адреса."""
    if not email or '@' not in email:
        return False
    return email.rsplit('@', 1)[-1].lower() in _PLACEHOLDER_DOMAINS


def placeholder_email(phone):
    """Унікальний placeholder-email з цифр телефону (або 'manual')."""
    base = re.sub(r'\D', '', phone or '') or 'manual'
    candidate = f'{base}@{PLACEHOLDER_EMAIL_DOMAIN}'
    n = 1
    while User.query.filter_by(email=candidate).first() is not None:
        n += 1
        candidate = f'{base}-{n}@{PLACEHOLDER_EMAIL_DOMAIN}'
    return candidate


def resolve_user(email, phone):
    """Знайти користувача за email або створити нового. Робить flush.

    Повертає (user, is_new). email вказано й знайдено -> reuse; вказано й
    не знайдено -> новий з цим email; не вказано -> новий з placeholder."""
    email = (email or '').strip().lower()
    if email:
        existing = User.query.filter_by(email=email).first()
        if existing is not None:
            return existing, False
    else:
        email = placeholder_email(phone)

    user = User(email=email, email_confirmed=False)
    db.session.add(user)
    db.session.flush()
    return user, True


def sync_user_and_profile(user, data):
    """Записати identity-поля у User і медичні -- у MedicalProfile.

    Порожні значення не затирають наявні. Email тут НЕ чіпаємо. Повертає
    profile."""
    _set_if(user, 'last_name', _strip_or_none(data.get('last_name')))
    _set_if(user, 'first_name', _strip_or_none(data.get('first_name')))

    profile = user.medical_profile
    if profile is None:
        profile = MedicalProfile(user_id=user.id, source=MedicalProfile.SOURCE_IMPORTED)
        db.session.add(profile)
        user.medical_profile = profile

    _set_if(profile, 'participant_type', data.get('participant_type') or None)
    _set_if(profile, 'middle_name', _strip_or_none(data.get('middle_name')))
    _set_if(profile, 'phone', _strip_or_none(data.get('phone')))
    if data.get('birth_date'):
        profile.birth_date = data['birth_date']
    _set_if(profile, 'education', _strip_or_none(data.get('education')))
    _set_if(profile, 'workplace', _strip_or_none(data.get('workplace')))
    _set_if(profile, 'position', _strip_or_none(data.get('position')))
    if data.get('specializations'):
        profile.specializations = list(data['specializations'])

    if profile.is_complete and profile.completed_at is None:
        profile.completed_at = datetime.now(timezone.utc)

    return profile


def apply_registration_fields(reg, data, profile):
    """Заповнити EventRegistration з data. Snapshot-поля (specialty,
    workplace) деривуємо з профілю -- консистентно з публічним флоу."""
    specs = profile.specializations or []
    specialty = ', '.join(labels_for_codes(specs)) or _strip_or_none(data.get('position')) or ''
    workplace = _strip_or_none(data.get('workplace')) or _strip_or_none(profile.workplace) or ''

    reg.phone = (_strip_or_none(data.get('phone')) or '')[:20]
    reg.specialty = _specialty_snapshot(specialty)
    reg.workplace = workplace[:300]
    reg.experience_years = data.get('experience_years')
    reg.license_number = _strip_or_none(data.get('license_number'))
    reg.status = data.get('status') or 'confirmed'
    reg.payment_status = data.get('payment_status') or 'unpaid'
    reg.payment_amount = data.get('payment_amount')
    reg.attended = bool(data.get('attended'))
    reg.cpd_points_awarded = data.get('cpd_points_awarded')
    reg.admin_notes = _strip_or_none(data.get('admin_notes'))


def _maybe_assign_place(reg):
    """Призначити номер місця для оплачених (не скасованих) реєстрацій."""
    if reg.payment_status == 'paid' and reg.status != 'cancelled' and reg.place_number is None:
        try:
            registration_service.assign_place_number(reg)
        except Exception:
            logger.exception('Failed to assign place_number for REG-%s', reg.id)


def upsert_participant(data, reg=None, on_duplicate='error'):
    """Створити або оновити учасника. Мутує сесію БЕЗ commit.

    Args:
        data: нормалізований dict (instance_id, last_name, first_name,
            middle_name, email, phone, participant_type, birth_date,
            education, workplace, position, specializations[list codes],
            status, payment_status, payment_amount, attended,
            cpd_points_awarded, experience_years, license_number, admin_notes).
        reg: наявний EventRegistration для редагування, або None (створення).
        on_duplicate: коли при створенні знайдено активну реєстрацію
            user+instance: 'error' (raise ParticipantError) | 'update'.

    Returns:
        (registration, was_created).
    """
    data = _normalize_data(data)

    # ----- EDIT -----
    if reg is not None:
        user = reg.user
        new_email = (data.get('email') or '').strip().lower()
        if new_email and new_email != user.email:
            clash = User.query.filter(
                User.email == new_email, User.id != user.id,
            ).first()
            if clash is not None:
                raise ParticipantError(
                    f'Email {new_email} вже належить іншому користувачу'
                )
            user.email = new_email
        profile = sync_user_and_profile(user, data)
        apply_registration_fields(reg, data, profile)
        db.session.flush()
        _maybe_assign_place(reg)
        return reg, False

    # ----- CREATE -----
    instance_id = data.get('instance_id')
    if not instance_id:
        raise ParticipantError('Не вказано захід')

    user, _is_new = resolve_user(data.get('email'), data.get('phone'))
    existing = registration_service.find_existing(user.id, instance_id)

    if existing is not None and existing.status != 'cancelled':
        if on_duplicate != 'update':
            raise ParticipantError('Цей учасник уже зареєстрований на цей захід')
        target = existing
    elif existing is not None:
        target = existing  # cancelled -> реактивуємо
    else:
        target = None  # нову реєстрацію створюємо ПІСЛЯ sync (див. нижче)

    # Профіль синхронізуємо ДО створення нової реєстрації: доступ до
    # user.medical_profile (lazy-load) тригерить autoflush, який інакше
    # вставив би ще не заповнений EventRegistration (null phone -> порушення
    # NOT NULL). Для наявної реєстрації target уже валідний у БД.
    profile = sync_user_and_profile(user, data)

    if target is None:
        target = EventRegistration(user_id=user.id, instance_id=instance_id)
        db.session.add(target)

    apply_registration_fields(target, data, profile)
    db.session.flush()
    _maybe_assign_place(target)

    return target, existing is None
