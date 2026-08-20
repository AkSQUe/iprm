"""Самостійне збереження анкети учасника: ПІБ + МОЗ-поля (№725 п.13).

Окремо від `participant_service`, який займається адмінським/xlsx upsert-ом
реєстрацій: тут людина редагує власні дані у своєму кабінеті, реєстрації не
створюються й адмін-керовані поля не чіпаються.

Окремо від `certificate_service`, який видає сертифікати: цей модуль лише
готує дані, з яких сертифікат потім виписується.

Транзакцією керує caller: функції змінюють і флашать сесію, але не комітять --
щоб маршрут міг обгорнути збереження власною обробкою помилок.
"""
from app.extensions import db
from app.models.certificate import Certificate
from app.models.medical_profile import MedicalProfile
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.specializations import labels_for_codes
from app.utils import normalize_name

# Поля, які учасник заповнює сам. Джерело правди для того, що приймає save().
NAME_FIELDS = ('last_name', 'first_name', 'middle_name')
PROFILE_FIELDS = ('participant_type', 'birth_date', 'education', 'workplace',
                  'position', 'specializations')


def has_issued_certificates(user):
    """Чи є в користувача хоч один невідкликаний сертифікат.

    EXISTS, а не завантаження рядків: відповідь потрібна лише як прапорець
    (показати попередження про зміну ПІБ), а сертифікатів може бути багато.
    """
    return bool(db.session.query(
        Certificate.query
        .filter_by(user_id=user.id, revoked=False)
        .exists()
    ).scalar())


def save(user, data):
    """Записати ПІБ у User і МОЗ-поля у MedicalProfile, створивши профіль за
    потреби. Бекфілить порожні снапшоти specialty/workplace у реєстраціях.

    `data` -- звичайний dict (не WTForm), щоб сервіс не залежав від форм:
    ключі NAME_FIELDS + PROFILE_FIELDS.

    Повертає dict: name_before, name_after, profile_complete, backfilled.
    Сесія лишається незакоміченою -- комітить caller.
    """
    name_before = user.full_name

    profile = user.medical_profile
    if profile is None:
        profile = MedicalProfile(user_id=user.id, source=MedicalProfile.SOURCE_SELF)
        db.session.add(profile)
        user.medical_profile = profile

    # normalize_name, а не голий strip: усі інші шляхи запису ПІБ (адмінка,
    # форма за токеном, xlsx-імпорт) йдуть через нього, а звідси ім'я
    # потрапляє у Certificate.recipient_name -- тобто на друкований
    # сертифікат. Без нормалізації там опинився б CAPS LOCK учасника.
    user.last_name = normalize_name(data.get('last_name'))
    user.first_name = normalize_name(data.get('first_name'))
    profile.middle_name = normalize_name(data.get('middle_name')) or None

    profile.participant_type = data.get('participant_type')
    profile.birth_date = data.get('birth_date')
    profile.education = (data.get('education') or '').strip() or None
    profile.workplace = (data.get('workplace') or '').strip() or None
    profile.position = (data.get('position') or '').strip() or None
    profile.specializations = list(data.get('specializations') or [])
    if profile.is_complete and profile.completed_at is None:
        profile.completed_at = utcnow()

    backfilled = _backfill_registration_snapshots(user, profile)
    db.session.flush()

    return {
        'name_before': name_before,
        'name_after': user.full_name,
        'profile_complete': profile.is_complete,
        'backfilled': backfilled,
    }


def _backfill_registration_snapshots(user, profile):
    """Заповнити порожні specialty/workplace в активних реєстраціях.

    Снапшоти знімаються на момент реєстрації і потрібні звітам БПР/xlsx;
    у тих, хто реєструвався до появи анкети, вони порожні. Уже заповнені НЕ
    чіпаємо -- це знімок на момент заходу, а не поточний стан людини.
    """
    specialty = ', '.join(
        labels_for_codes(profile.specializations or [])
    ) or (profile.position or '').strip()
    workplace = (profile.workplace or '').strip()
    if not specialty and not workplace:
        return 0

    regs = (
        EventRegistration.query
        .filter(
            EventRegistration.user_id == user.id,
            EventRegistration.status != 'cancelled',
        )
        .all()
    )
    touched = 0
    for reg in regs:
        changed = False
        if specialty and not (reg.specialty or '').strip():
            reg.specialty = specialty
            changed = True
        if workplace and not (reg.workplace or '').strip():
            reg.workplace = workplace
            changed = True
        if changed:
            touched += 1
    return touched
