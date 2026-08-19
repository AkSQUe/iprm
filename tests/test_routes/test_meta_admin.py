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
from app.models.meta_lead import MetaLead, MetaLeadEvent
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


# Порядок видалення в прибиранні: спершу діти, потім батьки.
_OWNED_MODELS = (
    MetaLeadEvent, MetaLead, EventRegistration, CourseInstance, Course, User,
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
