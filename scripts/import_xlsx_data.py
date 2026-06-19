"""Імпорт історичних даних з трьох .md-таблиць (експорт з xlsx):

  1. Розклади курсів.md      -> CourseInstance (Session ID S004..S043)
  2. Дані зареєстрованих.md  -> User (+ MedicalProfile) (User ID U0001..)
  3. Зареєстровані на захід.md-> EventRegistration (join User ID + Session ID)

Скрипт ідемпотентний і виконується в одній транзакції. За замовчуванням --
DRY-RUN (rollback наприкінці). Для запису: --apply.

Узгоджені рішення:
  * Розклад: "тільки додати + оновити збіги". Збіг = (course_id, ДАТА, location);
    Київ = location ''. Збіг -> status='completed' + ціна/формат/учасники.
    Решту наявних published-інстансів НЕ чіпаємо.
  * Користувачі БЕЗ пароля (немає AuthIdentity). email_confirmed=False.
    Відновлення пароля -- окремий крок (форгот-флоу ще не реалізовано).
  * Email порожній/не-email ("Інстаграм"/"Воронка"): якщо є телефон ->
    <digits>@xlsx.temp; інакше -- рядок-сміття, пропустити.
  * Дублікати email -> один User (перший виграє); усі User ID -> цей User.
  * Місто -> MedicalProfile.workplace (окремої колонки міста немає).
  * S001 (Базовий без дати) і S002 (Урологія -- курсу немає): ПРОПУСТИТИ
    разом із їхніми реєстраціями.

Запуск з кореня:
    python scripts/import_xlsx_data.py            # dry-run
    python scripts/import_xlsx_data.py --apply     # запис
"""
import re
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:  # консоль Windows за замовчуванням cp1251 -- друкуємо в UTF-8
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.course import Course  # noqa: E402
from app.models.course_instance import CourseInstance  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.medical_profile import MedicalProfile  # noqa: E402
from app.models.registration import EventRegistration  # noqa: E402

KYIV = timezone(timedelta(hours=3))
DEFAULT_TIME = (11, 0)
MAX_PARTICIPANTS = 20

FILE_SCHEDULE = ROOT / '1. Розклади курсів.md'
FILE_USERS = ROOT / '2. Дані зареєстрованих.md'
FILE_REGS = ROOT / '3. Зареєстровані на захід.md'

SKIP_SESSIONS = {'S001', 'S002'}

# Спеціалізація (професія у файлі) -> code з app/models/specializations.py.
SPEC_TO_CODE = {
    'Косметолог': 'cosmetology',
    'Ортопед-травматолог': 'orthopedics_traumatology',
    'Стоматолог': 'dentistry',
    'Гінеколог': 'obstetrics_gynecology',
    'Акушер-гінеколог': 'obstetrics_gynecology',
    'Невролог': 'neurology',
    'Хірург': 'surgery',
    'Дерматолог': 'dermatology',
    'Уролог': 'urology',
    'Терапевт': 'therapy',
    'Реабілітолог': 'rehabilitation',
    'Медсестра': 'nursing',
    'Лаборант': 'lab_assistant',
    'Сімейний лікар': 'family_medicine',
    'Педіатр': 'pediatrics',
    'Фізіотерапевт': 'physical_therapy',
    'Психіатр': 'psychiatry',
    'Пародонтолог': 'periodontics',
    'Кардіолог': 'cardiology',
    'Офтальмолог': 'ophthalmology',
    'Дієтолог': 'dietologist',
    # Немедичні/без коду -> 'other' (текст лишається в EventRegistration.specialty)
    'Психолог': 'other',
    'Психотерапевт': 'other',
    'Масажист': 'other',
    'Остеопат': 'other',
}


# ------------------------- парсинг .md-таблиць -------------------------
def parse_table(path):
    lines = path.read_text(encoding='utf-8').splitlines()
    rows = [l for l in lines if l.lstrip().startswith('|')]

    def cells(line):
        return [c.strip() for c in line.strip().strip('|').split('|')]

    header = cells(rows[0])
    out = []
    for line in rows[2:]:  # пропускаємо header + separator
        c = cells(line)
        if len(c) < len(header):
            c += [''] * (len(header) - len(c))
        out.append(dict(zip(header, c)))
    return out


# ------------------------- нормалізатори -------------------------
def parse_dt(s):
    s = (s or '').strip()
    if not s:
        return None
    m = re.match(r'(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?', s)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4)) if m.group(4) else DEFAULT_TIME[0]
    mm = int(m.group(5)) if m.group(5) else DEFAULT_TIME[1]
    return datetime(y, mo, d, hh, mm, tzinfo=KYIV)


def parse_decimal(s):
    s = (s or '').strip().replace(' ', '').replace(',', '.')
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def clean_email(raw):
    return (raw or '').replace('\\', '').replace(' ', '').strip().lower()


def phone_digits(raw):
    return re.sub(r'\D', '', raw or '')


def norm_phone(raw):
    return re.sub(r'[^\d+]', '', raw or '')[:20]


def split_name(pib):
    pib = (pib or '').replace('\\', '').strip()
    parts = pib.split()
    if not parts:
        return '', '', ''
    if len(parts) == 1:
        return '', parts[0], ''           # last, first, middle
    if len(parts) == 2:
        return parts[0], parts[1], ''
    return parts[0], parts[1], ' '.join(parts[2:])


def slug_for_title(title):
    t = title.lower()
    if 'терапевтична сила' in t:
        return 'avtorskyi-kurs-tsitaishvili'
    if 'плазмогель' in t:
        return 'plasomgel-v-estetichiy-medicini' if 'горизонт' in t else 'plazmogel-ruban'
    if 'узд' in t:
        return 'plazmoterapiya-v-ortopedii'
    if 'аутологічною плазмою' in t or 'prp' in t:
        return 'plazmoterapiya-v-stomatologii'
    if 'neuro-relax' in t or 'nrp' in t:
        return 'nrp-neuro-relax-protocol-offline' if 'офлайн' in t else 'nrp-neuro-relax-protocol'
    if 'базовий курс' in t:
        return 'bazovyi-kurs-z-postanovkoyu-ruky'
    if 'трихолог' in t:
        return 'plazmoterapiya-v-tryhologii-bondar'
    if 'гінеколог' in t:
        return 'plazmoterapiya-v-ginekologii'
    return None


def norm_location(raw):
    loc = (raw or '').strip()
    if loc.lower() in ('київ', 'киев', ''):
        return ''
    if loc.isupper():
        loc = loc.capitalize()
    return loc


# ------------------------- фази -------------------------
def phase_schedule(report):
    """Повертає session_map: Session ID -> CourseInstance."""
    course_by_slug = {c.slug: c for c in Course.query.all()}
    index = {}
    for inst in CourseInstance.query.all():
        if inst.start_date is None:
            continue
        key = (inst.course_id, inst.start_date.astimezone(KYIV).date(), inst.location or '')
        index.setdefault(key, inst)

    session_map = {}
    for row in parse_table(FILE_SCHEDULE):
        sid = row['Session ID']
        slug = slug_for_title(row['Курс'])
        course = course_by_slug.get(slug) if slug else None
        if not course:
            report['sched_skip'].append((sid, row['Курс'][:40], 'НЕМАЄ КУРСУ'))
            continue
        start = parse_dt(row['Дата початку'])
        end = parse_dt(row['Дата закінчення'])
        if end == start:
            end = None
        fmt = 'online' if row['Формат'].strip().lower().startswith('онлайн') else 'offline'
        price = parse_decimal(row['Ціна (UAH)'])
        location = norm_location(row['Локація'])

        key = (course.id, start.date(), location)
        inst = index.get(key)
        if inst:
            inst.status = 'completed'
            inst.event_format = fmt
            inst.max_participants = MAX_PARTICIPANTS
            inst.trainer_id = course.trainer_id
            if price is not None:
                inst.price = price
            if end is not None:
                inst.end_date = end
            report['sched_upd'].append((sid, start.date().isoformat(), location or 'Київ', slug))
        else:
            inst = CourseInstance(
                course_id=course.id, start_date=start, end_date=end,
                event_format=fmt, price=price, cpd_points=None,
                max_participants=MAX_PARTICIPANTS, trainer_id=course.trainer_id,
                status='completed', location=location,
            )
            db.session.add(inst)
            index[key] = inst
            report['sched_new'].append((sid, start.date().isoformat(), location or 'Київ', slug))
        session_map[sid] = inst

    db.session.flush()
    return session_map


def phase_users(report):
    """Повертає (user_map: User ID -> User, user_info: User ID -> dict)."""
    existing_by_email = {u.email: u for u in User.query.all()}
    email_to_user = {}      # email -> User (новий або наявний)
    user_map = {}
    user_info = {}
    pending_profiles = []   # (User, middle, code, phone, city)

    for row in parse_table(FILE_USERS):
        uid = row['User ID']
        pib = row['ПІБ']
        phone_raw = row['Телефон']
        spec_raw = row.get('Спеціалізація', '').strip()
        city = row.get('Місто', '').strip()

        email = clean_email(row['Email'])
        if '@' not in email:
            digits = phone_digits(phone_raw)
            if not digits:
                report['user_skip_junk'].append((uid, pib[:40]))
                continue
            email = f'{digits}@xlsx.temp'

        user_info[uid] = {
            'phone': norm_phone(phone_raw),
            'spec': spec_raw,
            'city': city,
        }

        if email in email_to_user:
            user_map[uid] = email_to_user[email]
            report['user_merged'].append((uid, email))
            continue

        existing = existing_by_email.get(email)
        if existing:
            email_to_user[email] = existing
            user_map[uid] = existing
            report['user_reused'].append((uid, email))
            continue

        last, first, middle = split_name(pib)
        user = User(email=email, first_name=first, last_name=last,
                    email_confirmed=False, is_active=True)
        db.session.add(user)
        email_to_user[email] = user
        user_map[uid] = user
        code = SPEC_TO_CODE.get(spec_raw, 'other') if spec_raw else None
        pending_profiles.append((user, middle, code, norm_phone(phone_raw), city))
        report['user_new'].append((uid, email))

    db.session.flush()  # призначає user.id

    for user, middle, code, phone, city in pending_profiles:
        db.session.add(MedicalProfile(
            user_id=user.id,
            source=MedicalProfile.SOURCE_IMPORTED,
            middle_name=middle or None,
            phone=phone or None,
            specializations=[code] if code else [],
            workplace=city or None,
        ))
    db.session.flush()
    return user_map, user_info


def phase_registrations(report, session_map, user_map, user_info):
    existing_regs = {
        (r.user_id, r.instance_id)
        for r in db.session.query(EventRegistration.user_id, EventRegistration.instance_id)
    }
    seen = set()
    for row in parse_table(FILE_REGS):
        uid = row['User ID']
        sid = row['Session ID']
        if sid in SKIP_SESSIONS:
            report['reg_skip_s12'] += 1
            continue
        inst = session_map.get(sid)
        if inst is None:
            report['reg_skip_nosession'] += 1
            continue
        user = user_map.get(uid)
        if user is None:
            report['reg_skip_nouser'] += 1
            continue

        key = (user.id, inst.id)
        if key in seen:
            report['reg_skip_dup'] += 1
            continue
        seen.add(key)
        if key in existing_regs:
            report['reg_kept'] += 1
            continue

        info = user_info.get(uid, {})
        status = 'confirmed' if row['Статус'].strip() == 'Підтверджено' else 'pending'
        paid = row['Оплата'].strip() == 'Оплачено'
        amount = parse_decimal(row['Сума'])
        reg_dt = parse_dt(row['Дата реєстрації'])
        event_dt = parse_dt(row['Дата заходу'])

        reg = EventRegistration(
            user_id=user.id,
            instance_id=inst.id,
            phone=(info.get('phone') or '')[:20],
            specialty=(info.get('spec') or '')[:200],
            workplace=(info.get('city') or '')[:300],
            status=status,
            payment_status='paid' if paid else 'unpaid',
            payment_amount=amount,
        )
        if reg_dt:
            reg.created_at = reg_dt
        if paid:
            reg.paid_at = event_dt or reg_dt
        manager = row.get('Менеджер', '').strip()
        reg.admin_notes = f'Імпорт з xlsx. Менеджер: {manager}'.strip()
        db.session.add(reg)
        report['reg_new'] += 1

    db.session.flush()


def main(apply):
    app = create_app()
    with app.app_context():
        report = {
            'sched_new': [], 'sched_upd': [], 'sched_skip': [],
            'user_new': [], 'user_reused': [], 'user_merged': [], 'user_skip_junk': [],
            'reg_new': 0, 'reg_kept': 0, 'reg_skip_s12': 0,
            'reg_skip_nosession': 0, 'reg_skip_nouser': 0, 'reg_skip_dup': 0,
        }

        session_map = phase_schedule(report)
        user_map, user_info = phase_users(report)
        phase_registrations(report, session_map, user_map, user_info)

        print('\n===== РОЗКЛАД =====')
        print(f'  оновлено (збіг -> completed): {len(report["sched_upd"])}')
        for sid, d, loc, slug in report['sched_upd']:
            print(f'    {sid}  {d}  {loc:<8} {slug}')
        print(f'  створено (нові completed): {len(report["sched_new"])}')
        for sid, d, loc, slug in report['sched_new']:
            print(f'    {sid}  {d}  {loc:<8} {slug}')
        if report['sched_skip']:
            print(f'  ПРОПУЩЕНО: {len(report["sched_skip"])}')
            for sid, t, why in report['sched_skip']:
                print(f'    {sid}  {why}  {t}')

        print('\n===== КОРИСТУВАЧІ =====')
        print(f'  створено нових:       {len(report["user_new"])}')
        print(f'  знайдено наявних:     {len(report["user_reused"])}')
        print(f'  обєднано (дублі):     {len(report["user_merged"])}')
        print(f'  пропущено (сміття):   {len(report["user_skip_junk"])}')
        for uid, pib in report['user_skip_junk']:
            print(f'    {uid}  {pib}')

        print('\n===== РЕЄСТРАЦІЇ =====')
        print(f'  створено:                 {report["reg_new"]}')
        print(f'  вже існували (kept):      {report["reg_kept"]}')
        print(f'  пропущено S001/S002:      {report["reg_skip_s12"]}')
        print(f'  пропущено (нема сесії):   {report["reg_skip_nosession"]}')
        print(f'  пропущено (нема юзера):   {report["reg_skip_nouser"]}')
        print(f'  пропущено (дубль у файлі):{report["reg_skip_dup"]}')

        if apply:
            db.session.commit()
            print('\n>>> ЗМІНИ ЗАСТОСОВАНО (commit).')
        else:
            db.session.rollback()
            print('\n>>> DRY-RUN: нічого не записано. Для запису: --apply')


if __name__ == '__main__':
    main(apply='--apply' in sys.argv)
