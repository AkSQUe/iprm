"""Розбір заявки Meta Lead Ads і прив'язка її до контакту.

Ядро інтеграції. Ціна помилки тут не «щось не показалось», а зшита з чужою
людиною картка: після хибного зіставлення менеджер дзвонить не тому, а
партнер отримує подію з чужим `iprm_user_id`. Тому кожне неоднозначне
місце тут або вирішується на користь «нічого не робити автоматично», або
піднімає `needs_attention` -- розбирає людина.

Три правила, які тримають цю ціну:

* **канонічний телефон -- лише український**. `normalize_phone` за власним
  докстрінгом на нерозпізнаному вводі повертає `'+<цифри>'`, і записати
  таке в ключ зіставлення означало б віддати `+3806784014070730886` як
  «канонічну форму» (див. коментар у `MedicalProfile._sync_phone_e164`).
  Не розпізнали -- `phone_e164 = None`, сирий рядок лишається в `phone_raw`;
* **автоматичного злиття контактів немає**. Телефон вказав на одну картку,
  пошта -- на іншу: прив'язуємо до телефонної, другу кладемо в
  `conflict_user_id`. Злиття незворотне, а помилка зіставлення -- ні;
* **`users.email` не перезаписується ніколи**. Це логін і унікальний ключ;
  нова адреса лягає в `MetaLead.alt_email` і показується менеджеру.

Модуль мутує сесію і **не комітить** -- як `participant_service`. Commit
робить викликач (черга `meta_lead_queue`), щоб подія, лід і контакт лягли
однією транзакцією. Партнерська подія тут теж не емітиться: її шле черга
ПІСЛЯ коміту, інакше партнер дізнався б про ліда, якого в нас відкотили.
"""
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.medical_profile import MedicalProfile
from app.models.meta_lead import MetaLead
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services.meta_contracts import ContactMatch, ParsedLead
from app.services.participant_service import is_placeholder_email, placeholder_email

logger = logging.getLogger(__name__)


# Стандартні поля інстант-форми Meta. Мапимо їх автоматично і НЕ робимо
# налаштовуваного мапінгу (рішення Q3): таблиця відповідностей «поле форми
# -> колонка» жила б окремо від самих форм і розсинхронізовувалась би при
# кожній новій кампанії, а полагодити її міг би лише той, хто пам'ятає, що
# вона є.
FIELD_EMAIL = 'email'
FIELD_PHONE = 'phone_number'
FIELD_FULL_NAME = 'full_name'
FIELD_FIRST_NAME = 'first_name'
FIELD_LAST_NAME = 'last_name'
FIELD_JOB_TITLE = 'job_title'
FIELD_COMPANY_NAME = 'company_name'

STANDARD_FIELDS = frozenset({
    FIELD_EMAIL, FIELD_PHONE, FIELD_FULL_NAME, FIELD_FIRST_NAME,
    FIELD_LAST_NAME, FIELD_JOB_TITLE, FIELD_COMPANY_NAME,
})

# `job_title` і `company_name` -- стандартні поля Meta, але в `ParsedLead`
# під них колонок немає, а контракт (`meta_contracts.py`) правити не можна.
# Тому вони лежать у `custom` під канонічними ключами: місце зберігання
# інше, обробка -- ні (їх читає `apply_lead_to_contact`, а не менеджер
# очима серед довільних відповідей).
PROFILE_FIELDS = (
    (FIELD_JOB_TITLE, 'position', 200),
    (FIELD_COMPANY_NAME, 'workplace', 300),
)

# Значення, за якими впізнаємо заявку з Lead Ads Testing Tool. Порівняння
# ТОЧНЕ і лише за іменами: підрядок зачепив би прізвище «Тестенко», а
# домен `example.com` -- половину наших же фікстур. Основний механізм
# позначки -- перемикач «режим тестування» в адмінці (рішення Q7); ця
# евристика лише страхує адміна, який його не увімкнув.
TEST_NAME_MARKERS = frozenset({
    'test', 'test lead', 'testlead', 'тест', 'тестовий лід', 'тестовий лид',
})

# Ліміти колонок, у які пишемо. Обрізаємо на нашому боці: довжина відповіді
# у формі Meta нічим не обмежена, а падіння на `value too long` у Postgres
# коштувало б усієї транзакції разом із подією черги.
_LIMITS = {
    'first_name': 120, 'last_name': 120, 'full_name': 255,
    'email': 255, 'phone_raw': 50,
}


class MetaIngestError(Exception):
    """Заявку неможливо розібрати (доменна помилка, показується в черзі)."""


# --- нормалізація ---------------------------------------------------------

def flatten_field_data(field_data):
    """Звести відповіді форми до `{name: value}`.

    Graph API віддає СПИСОК `{'name': ..., 'values': [...]}`, і значення
    завжди у списку -- навіть коли воно одне. Приймаємо і вже згорнутий
    dict: звірка й ручний повтор із адмінки подеколи мають на руках саме
    його, а два формати на вході дешевші за конвертер на кожному виклику.

    Кілька значень (multi-select) склеюємо через кому -- втратити відповідь
    гірше, ніж показати її одним рядком.
    """
    if not field_data:
        return {}

    if isinstance(field_data, dict):
        items = field_data.items()
    else:
        items = []
        for entry in field_data:
            if not isinstance(entry, dict):
                continue
            name = entry.get('name')
            if not name:
                continue
            items.append((name, entry.get('values', entry.get('value'))))

    flat = {}
    for name, value in items:
        key = str(name).strip()
        if not key:
            continue
        if isinstance(value, (list, tuple)):
            parts = [str(v).strip() for v in value if v not in (None, '')]
            text = ', '.join(p for p in parts if p)
        elif value is None:
            text = ''
        else:
            text = str(value).strip()
        flat[key] = text
    return flat


def normalize_field_data(field_data):
    """Розібрати відповіді форми у `ParsedLead`.

    Ім'я Meta віддає АБО одним полем `full_name`, АБО парою
    `first_name`/`last_name` -- залежно від того, як складена форма. Обидва
    шляхи мусять давати той самий результат, інакше та сама людина з двох
    різних кампаній виглядатиме як два різні записи в списку.
    """
    from app.utils import UA_PHONE_RE, normalize_name, normalize_phone

    flat = flatten_field_data(field_data)
    std, custom = {}, {}
    for name, value in flat.items():
        key = name.lower()
        if key in STANDARD_FIELDS:
            std[key] = value
        else:
            # Ключ лишаємо як його назвали у формі: саме за цим підписом
            # менеджер шукає відповідь у картці ліда.
            custom[name] = value

    email = (std.get(FIELD_EMAIL) or '').strip().lower() or None

    phone_raw = (std.get(FIELD_PHONE) or '').strip() or None
    normalized = normalize_phone(phone_raw) if phone_raw else None
    phone_e164 = normalized if normalized and UA_PHONE_RE.match(normalized) else None

    first_name = normalize_name(std.get(FIELD_FIRST_NAME)) or None
    last_name = normalize_name(std.get(FIELD_LAST_NAME)) or None
    full_name = normalize_name(std.get(FIELD_FULL_NAME)) or None

    if full_name and not (first_name or last_name):
        # Різати по ПЕРШОМУ пробілу: у "Олена Ковальчук-Іваненко" прізвище
        # одне, а в "Олена Марія Ковальчук" -- друге слово теж частина
        # прізвища для нас важливіша за здогадку про друге ім'я.
        parts = full_name.split(' ', 1)
        first_name = parts[0] or None
        last_name = (parts[1].strip() if len(parts) > 1 else '') or None
    elif not full_name and (first_name or last_name):
        full_name = ' '.join(p for p in (first_name, last_name) if p) or None

    for key, _attr, _limit in PROFILE_FIELDS:
        value = (std.get(key) or '').strip()
        if value:
            custom[key] = value

    return ParsedLead(
        email=_clip(email, _LIMITS['email']),
        phone_raw=_clip(phone_raw, _LIMITS['phone_raw']),
        phone_e164=phone_e164,
        first_name=_clip(first_name, _LIMITS['first_name']),
        last_name=_clip(last_name, _LIMITS['last_name']),
        full_name=_clip(full_name, _LIMITS['full_name']),
        custom=custom,
    )


# --- пошук контакту -------------------------------------------------------

def resolve_contact(email, phone_e164):
    """Знайти контакт під заявку. Порядок: телефон -> пошта -> створити.

    Телефон перший, бо в інстант-формі його підставляє сам Facebook із
    профілю, а пошту людина нерідко вписує робочу «щоб не спамили».

    `MedicalProfile.phone_e164` -- індекс, а НЕ unique: у проді один номер
    справді ділять два акаунти (клініка з єдиним контактним телефоном).
    Тож «точний збіг» цілком може дати кілька карток -- беремо найстарішу,
    решту віддаємо менеджеру в `extra_user_ids`.
    """
    email = (email or '').strip().lower() or None
    phone_e164 = (phone_e164 or '').strip() or None

    by_phone = _users_by_phone(phone_e164)
    by_email = User.query.filter(User.email == email).first() if email else None

    if by_phone:
        user = by_phone[0]
        extra = [u.id for u in by_phone[1:]]
        conflict = by_email if (by_email is not None and by_email.id != user.id) else None
        reasons = []
        if extra:
            reasons.append(
                f'Номер {phone_e164} мають ще контакти: '
                f'{", ".join("#%s" % i for i in extra)}. '
                f'Прив\'язано до найстарішого (#{user.id}).'
            )
        if conflict is not None:
            reasons.append(
                f'Пошта {email} належить контакту #{conflict.id}, '
                f'а номер -- контакту #{user.id}. Прив\'язано за номером; '
                f'злиття карток -- рішення менеджера.'
            )
        return ContactMatch(
            user=user, method=MetaLead.MATCH_PHONE, conflict_user=conflict,
            extra_user_ids=extra, reason=' '.join(reasons),
        )

    if by_email is not None:
        return ContactMatch(user=by_email, method=MetaLead.MATCH_EMAIL)

    # Контакт створює `ingest_lead`: тут ми лише читаємо базу, і сервіс
    # пошуку, що мовчки додає рядки, був би пасткою для будь-якого іншого
    # виклику (наприклад із адмінки -- «а хто це?»).
    return ContactMatch(method=MetaLead.MATCH_CREATED)


def _users_by_phone(phone_e164):
    """Контакти з цим канонічним номером, від найстарішого.

    Сортуємо в Python, а не `ORDER BY`: Postgres і SQLite розкладають NULL
    у `created_at ASC` по-різних кінцях, і «найстаріший» залежав би від
    того, де крутиться код. Записів тут одиниці -- ціни в цьому немає.
    """
    if not phone_e164:
        return []
    rows = (
        User.query
        .join(MedicalProfile, MedicalProfile.user_id == User.id)
        .filter(MedicalProfile.phone_e164 == phone_e164)
        .all()
    )
    return sorted(rows, key=lambda u: (u.created_at is None, u.created_at, u.id or 0))


# --- оновлення контакту ---------------------------------------------------

def apply_lead_to_contact(user, parsed):
    """Дописати в картку те, чого в ній ще немає. Мутує сесію без commit.

    Заповнені поля НЕ перезаписуються. Meta бере відповіді з профілю
    Facebook, а він буває десятирічної давності: «свіжіше» тут не означає
    «правдивіше», і місце роботи, яке лікар сам вписав при реєстрації на
    захід, важить більше за автопідстановку соцмережі.

    Це відрізняється від `participant_service._set_if`, який непорожнім
    значенням наявне таки затирає -- там джерело даних людина, а тут
    рекламна мережа.
    """
    _fill(user, 'first_name', _clip(parsed.first_name, 100))
    _fill(user, 'last_name', _clip(parsed.last_name, 100))

    profile = _ensure_profile(user)
    # Канонічну форму пишемо в `phone`, бо валідатор моделі виводить
    # `phone_e164` саме з нього. Нерозпізнаний номер лягає сирим -- людині
    # він потрібен, щоб передзвонити, а ключем зіставлення не стане.
    _fill(profile, 'phone', _clip(parsed.phone_e164 or parsed.phone_raw, 20))
    for key, attr, limit in PROFILE_FIELDS:
        _fill(profile, attr, _clip(parsed.custom.get(key), limit))


def _ensure_profile(user):
    profile = user.medical_profile
    if profile is not None:
        return profile
    if user.id is None:
        db.session.flush()
    profile = MedicalProfile(user_id=user.id, source=MedicalProfile.SOURCE_META)
    db.session.add(profile)
    user.medical_profile = profile
    return profile


def _fill(obj, attr, value):
    """Записати лише в порожнє поле."""
    if value in (None, ''):
        return
    current = getattr(obj, attr, None)
    if current in (None, ''):
        setattr(obj, attr, value)


# --- приймання ------------------------------------------------------------

def ingest_lead(raw_lead, *, event=None):
    """Розібрати відповідь Graph API у `MetaLead` і прив'язати контакт.

    Ідемпотентно за `leadgen_id`: знайшли наявний лід -- повертаємо його і
    нічого не чіпаємо. Meta повторює доставку вебхука при будь-якому
    сумніві, а звірка навмисно перечитує ті самі 48 годин, тож повтор тут
    не виняткова ситуація, а щоденна.

    `event` -- сира подія черги, з якої лід приїхав. Потрібна лише як
    джерело `page_id` і запасного `created_time`: у відповіді
    `GET /{leadgen_id}` їх немає, а у вебхуці є. Стан події (`status`,
    `lead_id`) ставить черга -- межа проходить тут.

    Мутує сесію БЕЗ commit.
    """
    raw_lead = dict(raw_lead or {})
    leadgen_id = str(raw_lead.get('id') or raw_lead.get('leadgen_id') or '').strip()
    if not leadgen_id:
        raise MetaIngestError('Відповідь Graph API без ідентифікатора ліда')

    existing = _find_lead(leadgen_id)
    if existing is not None:
        return existing

    flat = flatten_field_data(raw_lead.get('field_data'))
    parsed = normalize_field_data(flat)
    match = resolve_contact(parsed.email, parsed.phone_e164)

    user = match.user
    method = match.method
    reasons = [match.reason] if match.reason else []

    if user is None:
        if parsed.has_contacts:
            user = _create_contact(parsed)
        else:
            # Ні пошти, ні номера -- заводити картку нема на що: вона
            # ніколи ні з чим не зіставиться і лише засмітить /admin/users.
            method = MetaLead.MATCH_NONE
            reasons.append('Заявка без пошти й телефону -- контакт не створено.')

    alt_email = None
    is_repeat = False
    if user is not None:
        is_repeat = _has_previous_lead(user)
        apply_lead_to_contact(user, parsed)
        alt_email = _alt_email_for(user, parsed, method)
        if alt_email:
            reasons.append(_alt_email_reason(user, alt_email))

    lead = MetaLead(
        leadgen_id=leadgen_id,
        created_time=_created_time(raw_lead, event),
        page_id=_source_value(raw_lead, event, 'page_id'),
        form_id=_source_value(raw_lead, event, 'form_id'),
        form_name=_clip(raw_lead.get('form_name'), 255),
        campaign_id=_clip(raw_lead.get('campaign_id'), 64),
        campaign_name=_clip(raw_lead.get('campaign_name'), 255),
        adset_id=_clip(raw_lead.get('adset_id'), 64),
        adset_name=_clip(raw_lead.get('adset_name'), 255),
        ad_id=_source_value(raw_lead, event, 'ad_id'),
        ad_name=_clip(raw_lead.get('ad_name'), 255),
        platform=_clip(raw_lead.get('platform'), 10),
        is_organic=bool(raw_lead.get('is_organic')),
        field_data=flat,
        raw_lead=raw_lead,
        first_name=parsed.first_name,
        last_name=parsed.last_name,
        full_name=parsed.full_name,
        email=parsed.email,
        phone_raw=parsed.phone_raw,
        phone_e164=parsed.phone_e164,
        user_id=user.id if user is not None else None,
        match_method=method,
        conflict_user_id=match.conflict_user.id if match.conflict_user is not None else None,
        alt_email=alt_email,
        needs_attention=bool(reasons),
        attention_reason=' '.join(reasons) or None,
        is_repeat=is_repeat,
        is_test=_is_test_lead(parsed),
        status=MetaLead.STATUS_NEW,
    )

    # Контакт і його правки фіксуємо ДО вставки ліда: тоді в SAVEPOINT
    # нижче лежить рівно один INSERT, і його відкат не забирає з собою
    # створену картку.
    db.session.flush()

    try:
        with db.session.begin_nested():
            db.session.add(lead)
            db.session.flush()
    except IntegrityError:
        # Дві доставки того самого ліда в різних воркерах: пре-перевірка
        # вище їх не розводить -- обидві бачать порожньо. UNIQUE розводить.
        # Свій лід прибираємо з сесії, інакше commit викликача спробував би
        # вставити його ще раз і впав уже поза нашим контролем.
        if lead in db.session:
            db.session.expunge(lead)
        duplicate = _find_lead(leadgen_id)
        if duplicate is None:
            raise
        # У лог іде лише ідентифікатор -- вміст полів це персональні дані.
        logger.info('Meta lead %s already ingested by a parallel worker', leadgen_id)
        return duplicate

    return lead


def _find_lead(leadgen_id):
    """Наявний лід за ідентифікатором Meta. Окремою функцією, бо шукаємо
    двічі: перед вставкою і після її провалу на UNIQUE."""
    return MetaLead.query.filter_by(leadgen_id=leadgen_id).first()


def _create_contact(parsed):
    """Завести картку під заявку: `User` + порожній профіль з `source=meta`.

    Пошти може не бути, а `users.email` -- NOT NULL, UNIQUE і водночас
    логін. Тому placeholder із цифр телефону (`@noemail.invalid`, RFC 2606
    -- гарантовано недоставлюваний): такій адресі не можна слати листи, і
    `is_placeholder_email` це підтверджує на боці розсилок.
    """
    email = parsed.email or placeholder_email(parsed.phone_e164 or parsed.phone_raw)
    user = User(email=email, email_confirmed=False)
    db.session.add(user)
    db.session.flush()
    _ensure_profile(user)
    return user


def _has_previous_lead(user):
    """Чи зверталась ця людина раніше.

    Видалені заявки не рахуємо: лід прибирають або як тестовий, або на
    вимогу людини «видаліть мої дані», і в обох випадках позначка
    «повторне звернення» воскресила б факт, який ми щойно прибрали.
    """
    if user.id is None:
        return False
    return db.session.query(
        MetaLead.query
        .filter(MetaLead.user_id == user.id, MetaLead.deleted_at.is_(None))
        .exists()
    ).scalar()


def _alt_email_for(user, parsed, method):
    """Пошта заявки, що не збіглася з поштою контакту.

    Тільки для збігу за телефоном: при збігу за поштою вони рівні за
    побудовою, а щойно створеному контакту адресу з заявки й поставили.
    """
    if method != MetaLead.MATCH_PHONE or not parsed.email:
        return None
    if parsed.email == (user.email or '').strip().lower():
        return None
    return parsed.email


def _alt_email_reason(user, alt_email):
    if is_placeholder_email(user.email):
        return (
            f'Контакт #{user.id} має технічну адресу-заглушку, а заявка '
            f'принесла {alt_email}. Логін змінює менеджер -- автоматично '
            f'ми пошту не перезаписуємо.'
        )
    return (
        f'Заявка принесла пошту {alt_email}, у контакта #{user.id} інша. '
        f'Записано окремо: users.email -- це логін і унікальний ключ.'
    )


def _is_test_lead(parsed):
    """Чи вважати заявку тестовою.

    Надійного прапорця Graph API не віддає: ліди з Lead Ads Testing Tool
    приходять тим самим шляхом і виглядають як справжні. Тому основне
    джерело правди -- перемикач в адмінці (рішення Q7), а евристика лише
    страхує адміна, який забув його увімкнути.
    """
    if _test_mode_enabled():
        return True
    for value in (parsed.full_name, parsed.first_name, parsed.last_name):
        if value and value.strip().lower() in TEST_NAME_MARKERS:
            return True
    return False


def _test_mode_enabled():
    """Стан перемикача «режим тестування».

    Читаємо рядок напряму, а не через `SiteSettings.get()`: той на порожній
    базі робить commit, а модуль за контрактом не комітить -- інакше він
    зафіксував би половину транзакції викликача.
    """
    settings = db.session.get(SiteSettings, 1)
    return bool(settings is not None and settings.meta_test_mode)


def _source_value(raw_lead, event, key):
    """Поле джерела: спершу відповідь Graph API, потім сира подія.

    `page_id` у відповіді `GET /{leadgen_id}` відсутній -- він є лише у
    вебхуці. Без цього запасного шляху ліди звірки й вебхука мали б різний
    набір джерела, і фільтр адмінки за сторінкою половину з них не бачив би.
    """
    value = raw_lead.get(key)
    if value in (None, ''):
        payload = getattr(event, 'raw_payload', None) or {}
        value = getattr(event, key, None) or payload.get(key)
    return str(value) if value not in (None, '') else None


def _created_time(raw_lead, event):
    """Час подання заявки (UTC, tz-aware). Колонка NOT NULL -- без нього
    лід неможливо пріоритезувати за часом очікування."""
    for candidate in (raw_lead.get('created_time'),
                      getattr(event, 'created_time', None)):
        parsed = _parse_dt(candidate)
        if parsed is not None:
            return parsed
    logger.warning('Meta lead has no usable created_time, using now()')
    return datetime.now(timezone.utc)


_TZ_NO_COLON = re.compile(r'([+-]\d{2})(\d{2})$')


def _parse_dt(value):
    """Дата з Graph API або з вебхука у tz-aware UTC.

    Три форми в одному місці навмисно: Graph віддає `+0000` без двокрапки
    (до Python 3.11 `fromisoformat` таке не бере), вебхук -- unix-секунди,
    а SQLite повертає збережену дату взагалі без tzinfo, і порівняння з
    нею падає `TypeError` у найнесподіванішому місці.
    """
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) or str(value).lstrip('-').isdigit():
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    text = str(value).strip().replace('Z', '+00:00')
    text = _TZ_NO_COLON.sub(r'\1:\2', text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _clip(value, limit):
    if value in (None, ''):
        return None
    text = str(value).strip()
    return text[:limit] if text else None
