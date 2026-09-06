"""Приймальні тести Meta Lead Ads: вісім критеріїв із ТЗ, по одному на тест.

Ці тести НЕ дублюють частинні (`test_meta_webhook`, `test_meta_lead_ingest`,
`test_meta_lead_queue`, `test_meta_admin`). Ті перевіряють вузли: розбір
поля, класифікацію помилки, рендер сторінки. Тут перевіряється рівно те,
що замовник прочитає як «здано»: заявка з реклами проходить УВЕСЬ шлях
Meta -> вебхук -> черга -> воркер -> `MetaLead` -> реєстр адмінки, і
робить це так, як описано в критерії.

Тому кожен тест названо за критерієм, а докстрінг містить його
формулювання. Ніде не викликається `ingest_lead` напряму -- лід завжди
доставляється підписаним POST-ом на бойовий ендпоінт або добирається
звіркою, бо саме цей шлях і приймається.

**Доступів Meta немає** (розділ 8 плану), тож Graph API підміняється
`FakeMetaGraphClient` у названий шов `meta_lead_queue._client`. Це не
пом'якшення перевірки: вебхук, чергу, розбір, прив'язку контакту й адмінку
виконує справжній код, підробленою лишається тільки мережа. Критерій N1
через це доводиться не секундоміром на боці Meta, а тим, що весь шлях
проходиться за ОДИН прогін воркера й не містить жодного зовнішнього
очікування.

**Тести в наборі не ізольовані одне від одного** (розділ 6 плану:
`tests/conftest.py` збирає `options = dict(bind=connection, ...)` і ніколи
їх не застосовує, тож усе закомічене сервісами живе до кінця прогону).
Наслідки враховані:

* кожен тест бере власний `leadgen_id`, власний номер і власну адресу;
  перевірки рахують рядки ЗА НИМИ, а не за загальною кількістю в таблиці;
* чужі `pending`-події паркуються перед кожним тестом -- інакше залишок
  від тестів вебхука (старший за наші, а сортування `received_at ASC`)
  з'їдав би батч воркера, і падало б це лише в повному прогоні;
* власні рядки прибираються після кожного тесту, щоб не зсувати чужу
  пагінацію в реєстрі лідів.
"""
from tests.support.rbac import grant_role
import base64
import hashlib
import json
import random
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.extensions import db
from app.models.medical_profile import MedicalProfile
from app.models.meta_lead import MetaLead, MetaLeadEvent
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import meta_lead_queue as queue
from app.services.meta_graph_client import MetaGraphClient
from tests.support.fake_meta_graph import (
    FakeMetaGraphClient,
    make_field_data,
    make_lead,
    make_webhook_body,
    make_webhook_value,
    sign_webhook,
)

WEBHOOK_URL = '/api/webhooks/meta/leads'
APP_ID = '1122334455667788'
APP_SECRET = 'acceptance-app-secret'
VERIFY_TOKEN = 'acceptance-verify-token'
PAGE_ID = '555000111'
FORM_ID = '9988776655'

# Стеля критерію N1. Порівнюється з часом УСЬОГО шляху, а не окремого
# кроку: замовник міряє від «натиснув Надіслати» до «бачу в адмінці».
DELIVERY_BUDGET_SECONDS = 10.0

# Рядок налаштувань один на весь прогін і переживає відкат фікстури, тож
# після себе його треба повертати на місце поле за полем.
_SETTINGS_FIELDS = (
    'meta_leads_enabled', 'meta_app_id', 'meta_app_secret', 'meta_verify_token',
    'meta_page_token', 'meta_page_token_set_at', 'meta_page_id', 'meta_page_name',
    'meta_test_mode', 'meta_test_mode_since', 'meta_reconcile_lookback_hours',
    'meta_last_lead_at', 'meta_last_webhook_at', 'meta_last_reconcile_at',
    'meta_last_reconcile_status', 'meta_last_reconcile_error',
    'meta_token_valid', 'meta_token_checked_at', 'meta_token_expires_at',
    'meta_token_error',
)

# Порядок видалення: спершу події (посилаються на ліда), потім самі ліди.
_OWNED_MODELS = (MetaLeadEvent, MetaLead)


# --------------------------- фікстури ---------------------------

def _ids(model):
    return {row_id for (row_id,) in db.session.query(model.id).all()}


@pytest.fixture(autouse=True)
def isolate(app):
    """Прибрати чуже до тесту і своє після нього.

    Паркування чужих `pending`-подій -- не косметика: воркер бере
    найстаріші 25, а залишок від інших файлів старший за наші події, тож
    без цього наша заявка просто не дісталася б обробки.
    """
    MetaLeadEvent.query.filter(
        MetaLeadEvent.status.in_([MetaLeadEvent.STATUS_PENDING,
                                  MetaLeadEvent.STATUS_RETRYING])
    ).update({'status': MetaLeadEvent.STATUS_SKIPPED}, synchronize_session=False)
    db.session.commit()

    before = {model: _ids(model) for model in _OWNED_MODELS}
    settings = SiteSettings.get()
    saved = {name: getattr(settings, name) for name in _SETTINGS_FIELDS}

    yield

    db.session.rollback()
    for model in _OWNED_MODELS:
        for row in model.query.all():
            if row.id not in before[model]:
                db.session.delete(row)
        db.session.flush()
    settings = SiteSettings.get()
    for name, value in saved.items():
        setattr(settings, name, value)
    db.session.commit()


@pytest.fixture
def meta_env(app, monkeypatch):
    """Налаштована інтеграція + фейковий Graph API у названому шві."""
    settings = SiteSettings.get()
    settings.meta_leads_enabled = True
    settings.meta_app_id = APP_ID
    settings.meta_app_secret = APP_SECRET
    settings.meta_verify_token = VERIFY_TOKEN
    settings.meta_page_token = 'page-token-acceptance'
    settings.meta_page_id = PAGE_ID
    settings.meta_test_mode = False
    settings.meta_reconcile_lookback_hours = 48
    settings.meta_last_reconcile_at = None
    db.session.commit()

    fake = FakeMetaGraphClient(leads=[])
    monkeypatch.setattr(queue, '_client', lambda _settings: fake)
    return fake


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'meta-acc-adm-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Приймальний', last_name='Адмін', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    return user


# --------------------------- помічники ---------------------------

def _gid():
    """Унікальний leadgen_id -- див. докстрінг модуля."""
    return f'{uuid4().int % 10 ** 15:015d}'


def _phone():
    """Унікальний український номер: фіксований зіставився б із лишком
    від інших тестів, і падало б це лише в повному прогоні."""
    return f'+38067{random.randrange(10 ** 7):07d}'


def _email(tag):
    return f'{tag}-{uuid4().hex[:10]}@example.com'


def _iso(moment=None):
    """Час у формі Graph API: зсув без двокрапки, як його віддає Meta."""
    moment = moment or datetime.now(timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%S+0000')


def _post(client, body, secret=APP_SECRET, header=True):
    """POST рівно тими байтами, які підписані."""
    raw, signature = sign_webhook(body, secret)
    headers = {'Content-Type': 'application/json'}
    if header:
        headers['X-Hub-Signature-256'] = signature
    return client.post(WEBHOOK_URL, data=raw, headers=headers)


def _publish(fake, leadgen_id=None, **answers):
    """Покласти лід у Meta (у фейк), ще нічого нам не доставляючи."""
    leadgen_id = leadgen_id or _gid()
    fake.add_lead(make_lead(
        leadgen_id=leadgen_id,
        created_time=_iso(),
        form_id=FORM_ID,
        field_data=make_field_data(**answers),
    ))
    return leadgen_id


def _webhook_body(leadgen_id):
    """Тіло штовха leadgen -- лише ідентифікатори, як шле сама Meta."""
    return make_webhook_body([make_webhook_value(
        leadgen_id=leadgen_id, page_id=PAGE_ID, form_id=FORM_ID,
        created_time=int(datetime.now(timezone.utc).timestamp()),
    )], page_id=PAGE_ID)


def _deliver(client, fake, leadgen_id=None, **answers):
    """Заявку подано в Meta і доставлено нам вебхуком. Без обробки."""
    leadgen_id = _publish(fake, leadgen_id, **answers)
    response = _post(client, _webhook_body(leadgen_id))
    assert response.status_code == 200
    return leadgen_id


def _lead(leadgen_id):
    return MetaLead.query.filter_by(leadgen_id=leadgen_id).one_or_none()


def _events(leadgen_id):
    return MetaLeadEvent.query.filter_by(leadgen_id=leadgen_id).all()


def _contact(email=None, phone=None, created_at=None):
    """Наявна картка клієнта: `User` + `MedicalProfile`, як її створюють
    імпорт учасників і реєстрація на захід."""
    user = User(email=email or _email('contact'), first_name='Наявний')
    if created_at is not None:
        user.created_at = created_at
    db.session.add(user)
    db.session.flush()
    profile = MedicalProfile(user_id=user.id, source=MedicalProfile.SOURCE_IMPORTED)
    if phone:
        profile.phone = phone
    db.session.add(profile)
    user.medical_profile = profile
    db.session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


# ============================ критерій 1 ============================

def test_criterion_1_test_lead_reaches_admin_under_ten_seconds(client, meta_env, admin):
    """Тестовий лід доходить до адмінки менш ніж за 10 секунд.

    Доступів Meta немає, тож секундомір на їхньому боці недоступний.
    Критерій доводиться інакше: увесь шлях (підписаний POST -> черга ->
    один прогін воркера -> `MetaLead` -> реєстр адмінки) проходиться
    всередині одного тесту, БЕЗ жодного зовнішнього очікування -- ані
    затримки перед обробкою, ані другого прогону, ані `sleep`. Що
    лишається за межами вимірювання -- лише мережа до нашого сервера й
    хвилинний цикл планувальника, обидва відомі й не залежать від коду.
    """
    fake = meta_env
    _login(client, admin)
    surname = f'Швидкий{uuid4().hex[:6]}'
    leadgen_id = _gid()

    # Будь-який `sleep` на цьому шляху -- це і є «зовнішнє очікування»,
    # заради відсутності якого критерій і формулювався. Пастка стежить,
    # щоб його не додали пізніше «щоб не гнати Graph API».
    def _no_sleep(_seconds):
        raise AssertionError('Шлях доставки ліда не має права спати')

    original_sleep = time.sleep
    time.sleep = _no_sleep
    try:
        started = time.monotonic()

        _deliver(client, fake, leadgen_id,
                 full_name=f'Олена {surname}',
                 email=_email('fast'), phone_number=_phone())
        stats = queue.process_queue()

        lead = _lead(leadgen_id)
        assert lead is not None, 'заявка не доїхала до реєстру за один прогін'

        page = client.get('/admin/meta-leads')
        elapsed = time.monotonic() - started
    finally:
        time.sleep = original_sleep

    assert page.status_code == 200
    assert surname.encode() in page.data, 'заявки немає в реєстрі адмінки'
    assert elapsed < DELIVERY_BUDGET_SECONDS, f'{elapsed:.2f} с -- понад бюджет'

    # Один прогін воркера і рівно один похід у Graph API: якби шлях
    # потребував другого прогону, реальна доставка чекала б ще хвилину.
    assert stats['done'] == 1
    assert fake.calls.count(('get_lead', leadgen_id)) == 1
    event = _events(leadgen_id)[0]
    assert event.status == MetaLeadEvent.STATUS_DONE
    assert event.attempts == 1
    assert event.lead_id == lead.id


# ============================ критерій 2 ============================

def test_criterion_2_repeated_delivery_creates_no_duplicate(client, meta_env):
    """Повторна доставка того самого ліда не створює дубль.

    Meta повторює штовх при будь-якому сумніві -- таймаут, 5xx, а подеколи
    й після успішної відповіді. Перевіряються обидва місця, де дубль може
    з'явитися: черга (другий POST) і реєстр (другий прогін воркера вже
    після розбору).
    """
    fake = meta_env
    leadgen_id = _publish(fake, email=_email('repeat'), phone_number=_phone())
    body = _webhook_body(leadgen_id)

    assert _post(client, body).status_code == 200
    assert _post(client, body).status_code == 200
    assert len(_events(leadgen_id)) == 1, 'другий штовх завів другу подію'

    queue.process_queue()
    lead = _lead(leadgen_id)
    assert lead is not None

    # Третя доставка вже ПІСЛЯ розбору: подія та сама, лід той самий.
    assert _post(client, body).status_code == 200
    stats = queue.process_queue()

    assert len(_events(leadgen_id)) == 1
    assert MetaLead.query.filter_by(leadgen_id=leadgen_id).count() == 1
    assert _lead(leadgen_id).id == lead.id
    assert stats['done'] == 0, 'повтор розібрано вдруге'


# ============================ критерій 3 ============================

@pytest.mark.parametrize('style', ['e164', 'no_plus', 'local', 'spaces', 'brackets'])
def test_criterion_3_same_phone_any_format_hits_existing_card(client, meta_env, style):
    """Заявка з тим самим телефоном у будь-якому форматі чіпляється до
    наявної картки.

    Формат номера задає то Facebook із профілю, то сама людина руками, і
    жоден із них не питає нас про канонічну форму. Новий контакт тут був
    би не «зайвим рядком», а другою карткою на клієнта, якому вже дзвонили.
    """
    fake = meta_env
    # Той самий номер у п'яти написаннях. Цифри унікальні на прогін --
    # фіксований номер зіставився б із лишком від інших тестів, і падало б
    # це лише в повному прогоні.
    canonical = _phone()
    local = canonical[3:]
    written = {
        'e164': canonical,
        'no_plus': canonical[1:],
        'local': local,
        'spaces': f'{local[:3]} {local[3:6]} {local[6:8]} {local[8:]}',
        'brackets': f'({local[:3]}) {local[3:6]}-{local[6:8]}-{local[8:]}',
    }[style]

    existing = _contact(phone=canonical)
    users_before = User.query.count()

    leadgen_id = _deliver(client, fake, phone_number=written)
    queue.process_queue()

    lead = _lead(leadgen_id)
    assert lead is not None
    assert lead.phone_e164 == canonical, f'{written!r} не звівся до канонічної форми'
    assert lead.user_id == existing.id, f'{written!r} завів нову картку'
    assert lead.match_method == MetaLead.MATCH_PHONE
    assert User.query.count() == users_before, 'зайвий контакт'


# ============================ критерій 4 ============================

def test_criterion_4_unknown_number_creates_filled_contact(client, meta_env):
    """Заявка з невідомим номером створює новий контакт із заповненими
    полями.

    «Заповненими» -- не просто рядок у `users`: менеджер має кому
    подзвонити (телефон у канонічній формі в профілі), як звернутись
    (ім'я й прізвище) і звідки людина взялась (`source = meta`).
    """
    fake = meta_env
    phone = _phone()
    email = _email('newcontact')
    assert MedicalProfile.query.filter_by(phone_e164=phone).first() is None
    assert User.query.filter_by(email=email).first() is None

    leadgen_id = _deliver(client, fake, full_name='Ярина Мельник',
                          email=email, phone_number=phone)
    queue.process_queue()

    lead = _lead(leadgen_id)
    assert lead is not None
    assert lead.match_method == MetaLead.MATCH_CREATED

    contact = db.session.get(User, lead.user_id)
    assert contact is not None
    assert contact.email == email
    assert contact.first_name == 'Ярина'
    assert contact.last_name == 'Мельник'
    assert contact.medical_profile is not None
    assert contact.medical_profile.phone_e164 == phone
    assert contact.medical_profile.source == MedicalProfile.SOURCE_META
    # Ознака «створено з ліда», а не «звертався раніше».
    assert lead.is_repeat is False


# ============================ критерій 5 ============================

def test_criterion_5_phone_email_conflict_goes_to_manual_review(client, meta_env):
    """Конфлікт телефон/пошта не зливає контакти, а йде на ручний розбір.

    Номер веде на одну картку, пошта -- на іншу. Автоматичне злиття
    незворотне, а помилка зіставлення -- ні, тож заявка чіпляється до
    телефонної картки, друга кладеться в `conflict_user_id`, і рішення
    лишається за менеджером.
    """
    fake = meta_env
    phone = _phone()
    older = _contact(phone=phone,
                     created_at=datetime.now(timezone.utc) - timedelta(days=400))
    newer = _contact(email=_email('by-mail'),
                     created_at=datetime.now(timezone.utc) - timedelta(days=10))
    newer_email = newer.email
    users_before = User.query.count()

    leadgen_id = _deliver(client, fake, phone_number=phone, email=newer_email)
    queue.process_queue()

    lead = _lead(leadgen_id)
    assert lead is not None
    assert lead.match_method == MetaLead.MATCH_PHONE
    assert lead.user_id == older.id
    assert lead.conflict_user_id == newer.id
    assert lead.needs_attention is True
    assert lead.attention_reason and str(newer.id) in lead.attention_reason

    # Жодного злиття: обидві картки на місці, пошта нікому не переписана.
    assert User.query.count() == users_before
    db.session.refresh(older)
    db.session.refresh(newer)
    assert newer.email == newer_email
    assert older.email != newer_email
    # Нова адреса лежить окремо -- `users.email` це логін і унікальний ключ.
    assert lead.alt_email == newer_email


# ============================ критерій 6 ============================

@pytest.mark.parametrize('case', ['no_header', 'wrong_secret', 'garbage'])
def test_criterion_6_webhook_with_bad_signature_is_rejected(client, meta_env, case):
    """Вебхук з невалідним підписом відхиляється.

    Відхиляється саме тілом: 401 і НІЧОГО в черзі. Прийнята подія без
    підпису означала б, що будь-хто, знаючи URL, наллє нам карток у реєстр
    клієнтів.
    """
    fake = meta_env
    leadgen_id = _publish(fake, email=_email('forged'), phone_number=_phone())
    body = _webhook_body(leadgen_id)

    if case == 'no_header':
        response = _post(client, body, header=False)
    elif case == 'wrong_secret':
        response = _post(client, body, secret='not-the-app-secret')
    else:
        raw = json.dumps(body, separators=(',', ':')).encode('utf-8')
        response = client.post(WEBHOOK_URL, data=raw, headers={
            'Content-Type': 'application/json',
            'X-Hub-Signature-256': 'sha256=deadbeef',
        })

    assert response.status_code == 401
    assert _events(leadgen_id) == []

    # І обробляти нічого: воркер не має звідки взяти цей лід.
    queue.process_queue()
    assert _lead(leadgen_id) is None
    assert ('get_lead', leadgen_id) not in fake.calls


# ============================ критерій 7 ============================

def test_criterion_7_disabled_webhook_leads_arrive_via_reconcile(client, meta_env):
    """При вимкненому вебхуку заявки з'являються через звірку.

    Вимкнений вебхук -- не гіпотеза: Meta сама знімає підписку після серії
    невдалих доставок, і дізнаємось ми про це вже по тиші. Тому заявка
    моделюється так, як вона й виглядає в цьому разі -- лід у Meta є,
    штовха не було.
    """
    fake = meta_env
    leadgen_id = _publish(fake, full_name='Богдан Сич',
                          email=_email('silent'), phone_number=_phone())

    # Жодного POST: доставка мертва.
    assert _events(leadgen_id) == []
    queue.process_queue()
    assert _lead(leadgen_id) is None

    report = queue.reconcile()
    assert report['fetched'] >= 1
    assert report['created'] >= 1

    events = _events(leadgen_id)
    assert len(events) == 1
    assert events[0].source == MetaLeadEvent.SOURCE_RECONCILE

    queue.process_queue()
    lead = _lead(leadgen_id)
    assert lead is not None
    assert lead.full_name == 'Богдан Сич'

    # Повторна звірка тих самих 48 годин дублю не робить.
    again = queue.reconcile()
    assert again['created'] == 0
    assert len(_events(leadgen_id)) == 1
    assert MetaLead.query.filter_by(leadgen_id=leadgen_id).count() == 1


# ============================ критерій 8 ============================

def test_criterion_8_token_survives_restart_without_manual_refresh(app, meta_env):
    """Токен переживає перезапуск застосунку і не потребує ручного
    оновлення.

    Перезапуск моделюється тим, що від нього насправді залежить: гине
    процес -- гине сесія SQLAlchemy разом з identity map і всіма
    розшифрованими значеннями в пам'яті. `db.session.remove()` знищує рівно
    це. Переживає лише те, що лежить у БД, і ключ, виведений із
    `SECRET_KEY`, який процес читає з оточення при старті.

    «Не потребує ручного оновлення» перевіряється окремо: Page token,
    обміняний через довгоживучий User token, безстроковий (`expires_at = 0`
    у `debug_token`), і клієнт Graph API збирається після «перезапуску» без
    жодного втручання адміна.
    """
    fake = meta_env
    token = f'EAAGpage-{uuid4().hex}'

    settings = SiteSettings.get()
    settings.meta_page_token = token
    settings.meta_page_token_set_at = datetime.now(timezone.utc)
    db.session.commit()

    stored = db.session.execute(
        text('SELECT meta_page_token FROM site_settings WHERE id = 1')
    ).scalar()
    assert stored, 'токен не записався'
    assert token not in stored, 'токен лежить у базі відкритим текстом'

    # --- «перезапуск»: сесія, identity map і все розшифроване зникли ---
    db.session.remove()

    reloaded = SiteSettings.get()
    assert reloaded is not settings, 'об’єкт узявся з кешу сесії -- перевірка порожня'
    assert reloaded.meta_page_token == token
    assert reloaded.meta_page_token_is_set is True

    # Ключ не залежить від нічого процес-локального: він виводиться лише з
    # SECRET_KEY, який переживає рестарт разом із конфігом. Перевіряємо це
    # незалежно від моделі -- інакше тест лишався б зеленим і на випадковому
    # ключі, згенерованому при старті процесу.
    key = base64.urlsafe_b64encode(
        hashlib.sha256(app.config['SECRET_KEY'].encode()).digest())
    assert Fernet(key).decrypt(stored.encode()).decode() == token

    # Ручного втручання не потрібно: клієнт збирається, а сам токен
    # безстроковий.
    client = MetaGraphClient.from_settings(reloaded)
    assert client.access_token == token

    report = queue.check_token()
    assert report['valid'] is True
    assert report['permanent'] is True, 'токен строковий -- ротація стане ручною роботою'
    assert fake.calls.count(('debug_token',)) == 1
