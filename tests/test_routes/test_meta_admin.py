"""Адмінка лідів Meta Lead Ads.

Перевіряються не стільки рендери, скільки чотири межі, які легко перейти
непомітно:

  * тестові заявки сховані за замовчуванням -- інакше реєстр менеджера
    засмічують власні перевірки інтеграції;
  * перехід у «в роботі» фіксує `first_touch_at` -- це і є метрика
    швидкості першого дзвінка, без неї сторінка декоративна;
  * видалення заявки НЕ чіпає сиру подію (вона тримає ідемпотентність) і
    НЕ зносить контакт, у якого є інші сліди;
  * сторінка налаштувань відкривається без жодного налаштованого токена --
    саме на ній цей токен і отримують.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import requests

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.auth_identity import AuthIdentity
from app.models.meta_lead import MetaLead, MetaLeadEvent, MetaLeadForm
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


# Порядок видалення в прибиранні: спершу діти, потім батьки.
# AuthIdentity -- перед User: SQLite не має каскадів, і осиротіла
# password-identity протікає в чужі вибірки (валиться test_api_v1_clients,
# і лише в повному прогоні).
_OWNED_MODELS = (
    MetaLeadEvent, MetaLead, MetaLeadForm, EventRegistration, CourseInstance,
    Course, AuthIdentity, User,
)

# Налаштування -- рядок-одинак, спільний з усіма іншими тестами: його не
# видалиш, тож поля повертаємо на місце по одному.
_SETTINGS_FIELDS = (
    'meta_leads_enabled', 'meta_app_id', 'meta_app_secret', 'meta_verify_token',
    'meta_page_token', 'meta_page_id', 'meta_page_name', 'meta_test_mode',
    'meta_test_mode_since', 'meta_token_valid', 'meta_token_checked_at',
)


def _ids(model):
    return {row_id for (row_id,) in db.session.query(model.id).all()}


@pytest.fixture(autouse=True)
def cleanup(app):
    """Прибрати за собою те, що закомітили роути адмінки.

    Фікстура `db_session` у conftest відкочує лише НЕзакомічене, а кожна дія
    адмінки завершується справжнім `commit`. Без цього прибирання рядки цього
    файлу протікали б у чужі вибірки -- і падав би не цей тест, а сусідній
    (експорт учасників, звірка лідів), у якому дефекту немає.
    """
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
def admin(app):
    user = User.create_with_password(
        f'ml-adm-{_uid()}@test.com', 'password123',
        first_name='М', last_name='Адмін', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return user


@pytest.fixture
def plain_user(app):
    user = User.create_with_password(
        f'ml-usr-{_uid()}@test.com', 'password123',
        first_name='Б', last_name='Юзер', email_confirmed=True,
    )
    db.session.flush()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _make_lead(**kwargs):
    """Заявка з мінімально валідним набором полів."""
    params = {
        'leadgen_id': f'lg-{_uid()}',
        'created_time': datetime.now(timezone.utc) - timedelta(minutes=5),
        'form_id': '900',
        'form_name': 'Консультація',
        'campaign_id': '100',
        'campaign_name': 'Серпень',
        'platform': 'ig',
        'field_data': {'email': 'lead@example.com'},
        'first_name': 'Олена',
        'last_name': 'Ковальчук',
        'email': f'lead-{_uid()}@example.com',
        'phone_raw': '067 123 45 67',
        'status': MetaLead.STATUS_NEW,
    }
    params.update(kwargs)
    lead = MetaLead(**params)
    db.session.add(lead)
    db.session.flush()
    return lead


def _contact():
    """Контакт БЕЗ пароля -- саме такий створює прив'язка ліда."""
    user = User(email=f'contact-{_uid()}@example.com', first_name='Олена')
    db.session.add(user)
    db.session.flush()
    return user


# ----------------------------- доступ -----------------------------

@pytest.mark.parametrize('url', [
    '/admin/meta-leads', '/admin/meta-leads/events', '/admin/meta-leads/settings',
])
def test_pages_require_admin(client, plain_user, url):
    _login(client, plain_user)
    assert client.get(url).status_code in (302, 403, 404)


# ----------------------------- реєстр -----------------------------

def test_list_renders_and_filters(client, admin):
    _login(client, admin)
    target = _make_lead(first_name='Ярина', last_name='Мельник',
                        campaign_name='Серпень PRP')
    other = _make_lead(first_name='Богдан', last_name='Сич',
                       campaign_id='777', campaign_name='Липень')

    page = client.get('/admin/meta-leads')
    assert page.status_code == 200
    assert 'Мельник'.encode() in page.data
    assert 'Сич'.encode() in page.data

    filtered = client.get(f'/admin/meta-leads?campaign_id={target.campaign_id}')
    assert 'Мельник'.encode() in filtered.data
    assert 'Сич'.encode() not in filtered.data

    found = client.get('/admin/meta-leads?q=Мельник')
    assert 'Мельник'.encode() in found.data
    assert 'Сич'.encode() not in found.data
    assert other.id  # рядок лишився в базі, його просто не показали


def test_test_leads_hidden_by_default(client, admin):
    _login(client, admin)
    _make_lead(first_name='Тестовий', last_name='Лідов', is_test=True)

    hidden = client.get('/admin/meta-leads')
    assert 'Лідов'.encode() not in hidden.data

    shown = client.get('/admin/meta-leads?test=with')
    assert 'Лідов'.encode() in shown.data

    only = client.get('/admin/meta-leads?test=only')
    assert 'Лідов'.encode() in only.data


def test_wait_late_filter_matches_the_card(client, admin):
    """Картка «чекають понад годину» має вести на зріз, який її й дає.

    Число над списком і фільтр рахуються одним виразом (`_late_clause`);
    щойно вони розійдуться, картка почне обіцяти рядки, яких у списку немає.
    """
    _login(client, admin)
    _make_lead(first_name='Довго', last_name='Чекаєв',
               created_time=datetime.now(timezone.utc) - timedelta(hours=3))
    _make_lead(first_name='Щойно', last_name='Прийшов')

    page = client.get('/admin/meta-leads?wait=late')
    assert page.status_code == 200
    assert 'Чекаєв'.encode() in page.data
    assert 'Прийшов'.encode() not in page.data


def test_sort_wait_lifts_untouched_leads(client, admin):
    """`sort=wait` піднімає тих, до кого ще не дійшли руки.

    Саме це питання ставлять до реєстру щоранку, і відповідь мусить бути
    серверною: клієнтський сорт переставив би лише поточну сторінку.
    """
    _login(client, admin)
    _make_lead(first_name='Взяли', last_name='Вроботу',
               created_time=datetime.now(timezone.utc) - timedelta(hours=5),
               first_touch_at=datetime.now(timezone.utc),
               status=MetaLead.STATUS_IN_WORK)
    _make_lead(first_name='Ніхто', last_name='Незаймав',
               created_time=datetime.now(timezone.utc) - timedelta(hours=1))

    page = client.get('/admin/meta-leads?sort=wait').get_data(as_text=True)
    assert page.index('Незаймав') < page.index('Вроботу')


def test_list_prints_kyiv_time(client, admin):
    """Час у списку -- київський, а не UTC із колонки.

    Колонки лежать у UTC; без переведення заявка, створена о 00:40 київської
    ночі, показувалась би вчорашнім 21:40.
    """
    _login(client, admin)
    _make_lead(first_name='Часова', last_name='Мітка',
               created_time=datetime(2026, 8, 20, 6, 30, tzinfo=timezone.utc))

    page = client.get('/admin/meta-leads').get_data(as_text=True)
    assert '20.08.2026 09:30' in page


def test_export_returns_xlsx(client, admin):
    _login(client, admin)
    _make_lead(first_name='Експорт', last_name='Тестовий')
    response = client.get('/admin/meta-leads/export')
    assert response.status_code == 200
    assert 'spreadsheetml' in response.headers['Content-Type']


# --------------------------- перша реакція ---------------------------

def test_in_work_sets_first_touch(client, admin):
    _login(client, admin)
    lead = _make_lead()
    assert lead.first_touch_at is None

    response = client.post(f'/admin/meta-leads/{lead.id}', data={
        'status': MetaLead.STATUS_IN_WORK,
        'admin_notes': 'Передзвонив, чекає на дату',
    }, follow_redirects=True)
    assert response.status_code == 200

    refreshed = db.session.get(MetaLead, lead.id)
    assert refreshed.status == MetaLead.STATUS_IN_WORK
    assert refreshed.first_touch_at is not None
    assert refreshed.first_touch_by == admin.id


def test_first_touch_is_not_rewritten(client, admin):
    """Повернення заявки в роботу не переписує момент першої реакції."""
    _login(client, admin)
    first_touch = datetime.now(timezone.utc) - timedelta(days=1)
    lead = _make_lead(status=MetaLead.STATUS_CLOSED, first_touch_at=first_touch,
                      first_touch_by=admin.id)

    client.post(f'/admin/meta-leads/{lead.id}', data={
        'status': MetaLead.STATUS_IN_WORK, 'admin_notes': '',
    }, follow_redirects=True)

    refreshed = db.session.get(MetaLead, lead.id)
    assert refreshed.first_touch_at is not None
    # Порівнюємо з точністю до хвилини: SQLite віддає дату без tzinfo.
    assert abs(
        refreshed.first_touch_at.replace(tzinfo=timezone.utc) - first_touch
    ) < timedelta(minutes=1)


# ----------------------------- видалення -----------------------------

def test_delete_keeps_contact_with_registration(client, admin):
    """Тестовий лід прив'язався до живого клієнта -- клієнт лишається."""
    _login(client, admin)
    contact = _contact()
    course = Course(title='Плазмотерапія', slug=f'ml-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(course_id=course.id, status='published',
                              event_format='offline', location=f'Київ-{_uid()}')
    db.session.add(instance)
    db.session.flush()
    db.session.add(EventRegistration(
        user_id=contact.id, instance_id=instance.id, phone='+380671110001',
        specialty='T', workplace='Клініка', status='confirmed',
    ))
    lead = _make_lead(user_id=contact.id, is_test=True,
                      match_method=MetaLead.MATCH_CREATED)
    db.session.flush()

    client.post(f'/admin/meta-leads/{lead.id}/delete', follow_redirects=True)

    assert db.session.get(MetaLead, lead.id).is_deleted
    assert db.session.get(User, contact.id) is not None


def test_delete_removes_contact_created_by_lead(client, admin):
    """Контакт, який створила саме ця заявка й більше ніщо, іде з нею."""
    _login(client, admin)
    contact = _contact()
    contact_id = contact.id
    lead = _make_lead(user_id=contact_id, is_test=True,
                      match_method=MetaLead.MATCH_CREATED)

    client.post(f'/admin/meta-leads/{lead.id}/delete', follow_redirects=True)

    assert db.session.get(MetaLead, lead.id).is_deleted
    assert db.session.get(User, contact_id) is None


def test_delete_keeps_contact_matched_by_phone(client, admin):
    """Заявка лише причепилась до наявної картки -- картку не чіпаємо."""
    _login(client, admin)
    contact = _contact()
    lead = _make_lead(user_id=contact.id, is_test=True,
                      match_method=MetaLead.MATCH_PHONE)

    client.post(f'/admin/meta-leads/{lead.id}/delete', follow_redirects=True)

    assert db.session.get(User, contact.id) is not None


def test_delete_does_not_touch_raw_event(client, admin):
    """Сира подія переживає видалення заявки -- вона тримає ідемпотентність."""
    _login(client, admin)
    lead = _make_lead()
    event = MetaLeadEvent(
        leadgen_id=lead.leadgen_id, raw_payload={'leadgen_id': lead.leadgen_id},
        status=MetaLeadEvent.STATUS_DONE, lead_id=lead.id,
    )
    db.session.add(event)
    db.session.flush()
    event_id = event.id

    client.post(f'/admin/meta-leads/{lead.id}/delete', follow_redirects=True)

    survivor = db.session.get(MetaLeadEvent, event_id)
    assert survivor is not None
    assert survivor.lead_id is None
    assert survivor.status == MetaLeadEvent.STATUS_DONE


def test_restore_relinks_event(client, admin):
    _login(client, admin)
    lead = _make_lead()
    event = MetaLeadEvent(
        leadgen_id=lead.leadgen_id, raw_payload={}, lead_id=lead.id,
        status=MetaLeadEvent.STATUS_DONE,
    )
    db.session.add(event)
    db.session.flush()

    client.post(f'/admin/meta-leads/{lead.id}/delete', follow_redirects=True)
    client.post(f'/admin/meta-leads/{lead.id}/restore', follow_redirects=True)

    assert not db.session.get(MetaLead, lead.id).is_deleted
    assert db.session.get(MetaLeadEvent, event.id).lead_id == lead.id


def test_bulk_delete_test_leads(client, admin):
    _login(client, admin)
    test_lead = _make_lead(is_test=True)
    real_lead = _make_lead(is_test=False)

    client.post('/admin/meta-leads/delete-test', follow_redirects=True)

    assert db.session.get(MetaLead, test_lead.id).is_deleted
    assert not db.session.get(MetaLead, real_lead.id).is_deleted


def test_bulk_delete_applies_the_same_contact_limits(client, admin):
    """Пакетне прибирання тримає ті самі межі, що й поодиноке видалення.

    Перевірка «чи можна знести контакт» стала батчевою (чотири запити на
    весь пакет замість чотирьох на рядок) -- і це найлегше місце, де вона
    могла б розійтися з поодинокою: контакт зі слідами мусить вижити.
    """
    _login(client, admin)

    orphan = _contact()
    orphan_id = orphan.id
    _make_lead(is_test=True, user_id=orphan_id,
               match_method=MetaLead.MATCH_CREATED)

    busy = _contact()
    busy_id = busy.id
    course = Course(title=f'Курс {_uid()}', slug=f'kurs-{_uid()}')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(course_id=course.id,
                              start_date=datetime.now(timezone.utc),
                              event_format='offline', location=f'Київ-{_uid()}')
    db.session.add(instance)
    db.session.flush()
    db.session.add(EventRegistration(
        user_id=busy_id, instance_id=instance.id, phone='+380671110002',
        specialty='T', workplace='Клініка', status='confirmed',
    ))
    _make_lead(is_test=True, user_id=busy_id,
               match_method=MetaLead.MATCH_CREATED)
    db.session.flush()

    client.post('/admin/meta-leads/delete-test', follow_redirects=True)

    assert db.session.get(User, orphan_id) is None
    assert db.session.get(User, busy_id) is not None



def test_bulk_delete_keeps_contact_with_password(client, admin):
    """Пароль -- такий самий слід, як реєстрація.

    Перевірка пароля стала батчевою (запит до `auth_identities` на весь
    пакет замість `User.has_password` на кожен рядок), і це рівно те місце,
    де батч міг би розійтися з поодинокою перевіркою: контакт, який уже
    вміє входити, мусить пережити прибирання тестових заявок.
    """
    _login(client, admin)

    with_password = User.create_with_password(
        f'ml-pwd-{_uid()}@example.com', 'password123', first_name='Ніна',
    )
    db.session.flush()
    kept_id = with_password.id
    _make_lead(is_test=True, user_id=kept_id,
               match_method=MetaLead.MATCH_CREATED)
    db.session.flush()

    client.post('/admin/meta-leads/delete-test', follow_redirects=True)

    assert db.session.get(User, kept_id) is not None


def _count_selects(fn):
    from sqlalchemy import event

    counted = []

    def _count(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith('SELECT'):
            counted.append(statement)

    event.listen(db.engine, 'before_cursor_execute', _count)
    try:
        fn()
    finally:
        event.remove(db.engine, 'before_cursor_execute', _count)
    return len(counted)


def test_removable_contacts_check_does_not_grow_with_pack_size(app):
    """Перевірка «які контакти підуть під ніж» коштує однаково на будь-який пакет.

    Міряємо саме перевірку, а не весь POST: сам `db.session.delete(user)`
    законно дорожчає з кількістю контактів, бо ORM вантажить зв'язки заради
    каскадів. А от РІШЕННЯ, кого видаляти, мусить бути пакетним -- і воно
    таким не було: `User.has_password` б'є в `auth_identities` на кожного
    вцілілого, тож обіцяні п'ять запитів були п'ять плюс довжина пакета.
    """
    from app.admin.routes_meta_leads import _bulk_removable_contacts

    small = [_make_lead(is_test=True, user_id=_contact().id,
                        match_method=MetaLead.MATCH_CREATED)
             for _ in range(1)]
    big = [_make_lead(is_test=True, user_id=_contact().id,
                      match_method=MetaLead.MATCH_CREATED)
           for _ in range(8)]
    db.session.flush()

    cheap = _count_selects(lambda: _bulk_removable_contacts(small))
    dear = _count_selects(lambda: _bulk_removable_contacts(big))

    assert len(_bulk_removable_contacts(big)) == 8, 'усі вісім мали б піти'
    assert cheap == dear, (
        f'пакет із восьми коштує {dear} запитів проти {cheap} на одному -- '
        'перевірка контакту знову поштучна'
    )


# ----------------------------- розмітка реєстру -----------------------------

def test_sorted_column_reports_its_state(client, admin):
    """Стрілку сортування видно оком, а `aria-sort` -- диктором.

    Заголовки малюються лише разом із таблицею, тож заявка тут обов'язкова:
    на порожньому реєстрі сторінка показує `admin-empty`, і перевіряти було
    б нічого.
    """
    _login(client, admin)
    _make_lead()
    db.session.flush()

    body = client.get('/admin/meta-leads?sort=wait').get_data(as_text=True)
    # Атрибут несуть лише сортовні заголовки (їх два): на несортовній
    # колонці `aria-sort` не має стояти взагалі -- навіть зі значенням
    # "none", бо воно означає «сортувати можна, зараз не відсортовано».
    assert body.count('aria-sort="other"') == 1, 'рівно одна колонка сортована'
    assert body.count('aria-sort="none"') == 1, 'друга сортовна -- поки ні'


def test_stat_card_marks_the_slice_you_are_in(client, admin):
    """Картка-зріз, у яку перейшли, мусить бути позначена.

    Рахуємо позначку саме на картці, а не голий `aria-current`: останній є
    ще й у навігації сайдбару, і його лічильник міряв би не те. Регулярка, а
    не підрядок: у картки зі своїм тоном клас складений
    (`admin-stat-card admin-stat-card--danger is-active`).
    """
    import re

    _login(client, admin)
    _make_lead(created_time=datetime.now(timezone.utc) - timedelta(hours=3))
    db.session.flush()
    marked = re.compile(r'class="admin-stat-card[^"]* is-active[^"]*"')

    plain = client.get('/admin/meta-leads').get_data(as_text=True)
    assert len(marked.findall(plain)) == 1, 'без фільтрів обрано «Усього заявок»'

    late = client.get('/admin/meta-leads?wait=late').get_data(as_text=True)
    assert len(marked.findall(late)) == 1, 'у зрізі «понад годину» -- саме він'
    assert 'admin-stat-card--danger is-active' in late


# ----------------------------- сира черга -----------------------------

def test_events_page_and_retry(client, admin):
    _login(client, admin)
    event = MetaLeadEvent(
        leadgen_id=f'lg-{_uid()}', raw_payload={},
        status=MetaLeadEvent.STATUS_FAILED, attempts=5,
        last_error='Meta 400 code=190',
        next_retry_at=datetime.now(timezone.utc),
    )
    db.session.add(event)
    db.session.flush()

    export = client.get('/admin/meta-leads/events/export')
    assert export.status_code == 200
    assert 'spreadsheetml' in export.headers['Content-Type']

    page = client.get('/admin/meta-leads/events')
    assert page.status_code == 200
    assert event.leadgen_id.encode() in page.data

    client.post(f'/admin/meta-leads/events/{event.id}/retry',
                follow_redirects=True)

    refreshed = db.session.get(MetaLeadEvent, event.id)
    assert refreshed.status == MetaLeadEvent.STATUS_PENDING
    assert refreshed.next_retry_at is None
    assert refreshed.attempts == 0
    # Текст помилки лишається: доки нова спроба його не перезапише, це
    # єдина підказка, чому подія впала.
    assert refreshed.last_error


# --------------------------- картка контакту ---------------------------

def test_user_detail_shows_meta_leads(client, admin):
    _login(client, admin)
    contact = _contact()
    _make_lead(user_id=contact.id, campaign_name='Кампанія Контакту')

    page = client.get(f'/admin/users/{contact.id}')
    assert page.status_code == 200
    assert 'Кампанія Контакту'.encode() in page.data
    assert contact.email.encode() in page.data


def test_user_detail_unknown_redirects(client, admin):
    _login(client, admin)
    assert client.get('/admin/users/99999999').status_code == 302


# --------------------------- підписи форми ---------------------------

def test_card_shows_form_labels_instead_of_meta_keys(client, admin):
    """Дефект, з якого це почалося: у картці були ключі, а не текст форми.

    `field_data` тут -- дослівно те, що віддає Graph API: для питання з
    варіантами він кладе КЛЮЧ (`ортопедія_/_травматологія`), а не підпис.
    """
    from app.services import meta_form_schema
    from tests.support.fake_meta_graph import make_form

    meta_form_schema.save_form(make_form('900'))
    db.session.flush()
    lead = _make_lead(form_id='900', field_data={
        'email': 'lead@example.com',
        'ваша_спеціальність?': 'ортопедія_/_травматологія',
        'чи_працюєте_ви_з_пацієнтами_після_бойових_ушкоджень?': 'так,_іноді',
    })

    _login(client, admin)
    page = client.get(f'/admin/meta-leads/{lead.id}')

    assert page.status_code == 200
    body = page.data.decode()
    assert 'Ваша спеціальність?' in body
    assert 'Ортопедія / травматологія' in body
    assert 'Так, іноді' in body
    assert 'ортопедія_/_травматологія' not in body
    # Пошта показана окремим полем -- у списку питань її бути не має.
    assert '<label>email</label>' not in body


def test_card_reads_without_schema_too(client, admin):
    """Схеми ще не забирали -- картка мусить читатись, а не показувати ключі."""
    lead = _make_lead(form_id='форма-без-схеми', field_data={
        'ваша_спеціальність?': 'ортопедія_/_травматологія',
    })

    _login(client, admin)
    body = client.get(f'/admin/meta-leads/{lead.id}').data.decode()

    assert 'Ваша спеціальність?' in body
    assert 'Ортопедія / травматологія' in body


def test_sync_forms_button_saves_schemas(client, admin, monkeypatch):
    """Кнопка бекфілу: один прогін лагодить одразу всі наявні картки."""
    from app.admin import routes_meta_leads
    from tests.support.fake_meta_graph import FakeMetaGraphClient, make_form

    settings = SiteSettings.get()
    settings.meta_page_id = '555000111'
    db.session.flush()

    fake = FakeMetaGraphClient(forms=[make_form('901'), make_form('902')])
    monkeypatch.setattr(routes_meta_leads, '_client', lambda *a, **kw: fake)

    _login(client, admin)
    page = client.post('/admin/meta-leads/settings/sync-forms',
                       follow_redirects=True)

    assert page.status_code == 200
    assert MetaLeadForm.query.filter_by(form_id='901').first() is not None
    assert MetaLeadForm.query.filter_by(form_id='902').first() is not None


def test_sync_forms_needs_page_id(client, admin):
    """Без ID Сторінки питати нема про що -- і в Graph API ми не йдемо."""
    settings = SiteSettings.get()
    settings.meta_page_id = ''
    db.session.flush()

    _login(client, admin)
    page = client.post('/admin/meta-leads/settings/sync-forms',
                       follow_redirects=True)

    assert page.status_code == 200
    assert MetaLeadForm.query.count() == 0


# --------------------------- налаштування ---------------------------

def test_settings_opens_without_token(client, admin):
    """Сторінка мусить відкриватись до будь-якого налаштування.

    Саме на ній токен і отримують -- сувора перевірка зробила б перший крок
    неможливим.
    """
    settings = SiteSettings.get()
    settings.meta_leads_enabled = False
    settings.meta_app_id = ''
    settings.meta_app_secret = ''
    settings.meta_page_token = ''
    db.session.flush()

    _login(client, admin)
    page = client.get('/admin/meta-leads/settings')
    assert page.status_code == 200
    assert 'Meta Lead Ads'.encode() in page.data


def test_settings_save_keeps_secret_when_blank(client, admin):
    settings = SiteSettings.get()
    settings.meta_app_secret = 'super-secret'
    db.session.flush()

    _login(client, admin)
    client.post('/admin/meta-leads/settings/save', data={
        'app_id': '123456', 'app_secret': '', 'verify_token': '',
        'page_id': '777', 'graph_version': 'v21.0',
        'reconcile_interval_minutes': '30', 'reconcile_lookback_hours': '48',
        'silence_alert_hours': '24', 'error_alert_threshold': '5',
        'enabled': 'y',
    }, follow_redirects=True)

    refreshed = SiteSettings.get()
    assert refreshed.meta_app_id == '123456'
    assert refreshed.meta_app_secret == 'super-secret'
    assert refreshed.meta_leads_enabled is True


def test_test_mode_toggle(client, admin):
    settings = SiteSettings.get()
    settings.meta_test_mode = False
    settings.meta_test_mode_since = None
    db.session.flush()

    _login(client, admin)
    client.post('/admin/meta-leads/settings/test-mode', follow_redirects=True)
    assert SiteSettings.get().meta_test_mode is True
    assert SiteSettings.get().meta_test_mode_since is not None

    client.post('/admin/meta-leads/settings/test-mode', follow_redirects=True)
    assert SiteSettings.get().meta_test_mode is False


def test_send_test_event_signs_payload(client, admin, monkeypatch):
    """Тестова подія йде публічним URL і несе коректний підпис."""
    import hashlib
    import hmac
    import json

    settings = SiteSettings.get()
    settings.meta_app_secret = 'app-secret-value'
    settings.meta_page_id = '555'
    db.session.flush()

    sent = {}

    class _Response:
        status_code = 200

    def _fake_post(url, data=None, headers=None, timeout=None):
        sent['url'] = url
        sent['data'] = data
        sent['headers'] = headers
        return _Response()

    monkeypatch.setattr(requests, 'post', _fake_post)

    _login(client, admin)
    response = client.post('/admin/meta-leads/settings/test-event', data={
        'leadgen_id': 'lg-manual-1', 'form_id': '900',
    }, follow_redirects=True)
    assert response.status_code == 200

    assert sent['url'].endswith('/api/webhooks/meta/leads')
    expected = hmac.new(b'app-secret-value', sent['data'],
                        hashlib.sha256).hexdigest()
    assert sent['headers']['X-Hub-Signature-256'] == f'sha256={expected}'

    payload = json.loads(sent['data'])
    change = payload['entry'][0]['changes'][0]
    assert change['field'] == 'leadgen'
    assert change['value']['leadgen_id'] == 'lg-manual-1'


def test_send_test_event_without_secret(client, admin, monkeypatch):
    """Без App Secret підпис порахувати нічим -- нікуди й не ходимо."""
    settings = SiteSettings.get()
    settings.meta_app_secret = ''
    db.session.flush()

    def _boom(*args, **kwargs):
        raise AssertionError('запит не мав відбутись')

    monkeypatch.setattr(requests, 'post', _boom)

    _login(client, admin)
    response = client.post('/admin/meta-leads/settings/test-event',
                           data={}, follow_redirects=True)
    assert response.status_code == 200
