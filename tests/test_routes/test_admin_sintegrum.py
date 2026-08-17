"""Адмінка Sintegrum: налаштування інтеграції і каталог онлайн-курсів.

Головне, що тут перевіряється, -- не рендер, а два запобіжники: ключ API не
витікає в HTML і не затирається порожнім полем, а курс без ціни чи посилання
не можна опублікувати навіть POST-ом в обхід форми.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.online_course import OnlineCourse
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import sintegrum_client as sc


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'as-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='А', last_name='Адмін', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return user


@pytest.fixture
def plain_user(app):
    user = User.create_with_password(
        f'pu-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Б', last_name='Юзер', email_confirmed=True,
    )
    db.session.flush()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


@pytest.fixture
def course(app):
    item = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Плазмотерапія',
        slug=f'oc-{uuid4().hex[:8]}',
        remote_status=1,
    )
    db.session.add(item)
    db.session.flush()
    yield item
    db.session.delete(item)
    db.session.flush()


@pytest.fixture
def settings(app):
    site = SiteSettings.get()
    site.sintegrum_api_base_url = 'https://api.sintegrum.com'
    site.sintegrum_company_alias = 'multimededu'
    site.sintegrum_enabled = False
    db.session.flush()
    return site


# ----------------------------- доступ -----------------------------

@pytest.mark.parametrize('url', [
    '/admin/sintegrum', '/admin/online-courses',
])
def test_pages_require_admin(client, plain_user, url):
    _login(client, plain_user)
    assert client.get(url).status_code in (302, 403, 404)


def test_pages_render_for_admin(client, admin, course, settings):
    _login(client, admin)
    assert client.get('/admin/sintegrum').status_code == 200
    assert client.get('/admin/online-courses').status_code == 200
    assert client.get(f'/admin/online-courses/{course.id}').status_code == 200


# ----------------------------- ключ API -----------------------------

def test_api_key_never_appears_in_html(client, admin, settings):
    settings.sintegrum_api_key = 'super-secret-value'
    db.session.flush()
    _login(client, admin)

    body = client.get('/admin/sintegrum').get_data(as_text=True)
    assert 'super-secret-value' not in body
    # Маска показує лише хвіст.
    assert '****alue' in body


def test_blank_key_field_keeps_existing_key(client, admin, settings):
    settings.sintegrum_api_key = 'keep-me'
    db.session.flush()
    _login(client, admin)

    client.post('/admin/sintegrum/save', data={
        'base_url': 'https://api.sintegrum.com',
        'company_alias': 'multimededu',
        'api_key': '',
        'sync_interval': '60',
        'access_ttl': '72',
    }, follow_redirects=True)

    assert SiteSettings.get().sintegrum_api_key == 'keep-me'


def test_new_key_replaces_and_stamps_date(client, admin, settings):
    settings.sintegrum_api_key = 'old'
    db.session.flush()
    _login(client, admin)

    client.post('/admin/sintegrum/save', data={
        'base_url': 'https://api.sintegrum.com',
        'company_alias': 'multimededu',
        'api_key': 'brand-new',
        'sync_interval': '60',
        'access_ttl': '72',
    }, follow_redirects=True)

    site = SiteSettings.get()
    assert site.sintegrum_api_key == 'brand-new'
    assert site.sintegrum_api_key_set_at is not None


# ----------------------------- валідація налаштувань -----------------------------

def test_cannot_enable_without_key(client, admin, settings):
    settings.sintegrum_api_key = ''
    db.session.flush()
    _login(client, admin)

    client.post('/admin/sintegrum/save', data={
        'base_url': 'https://api.sintegrum.com',
        'company_alias': 'multimededu',
        'api_key': '',
        'enabled': 'on',
        'sync_interval': '60',
        'access_ttl': '72',
    }, follow_redirects=True)

    assert SiteSettings.get().sintegrum_enabled is False


def test_http_base_url_rejected(client, admin, settings):
    _login(client, admin)
    client.post('/admin/sintegrum/save', data={
        'base_url': 'http://api.sintegrum.com',
        'company_alias': 'multimededu',
        'sync_interval': '60',
        'access_ttl': '72',
    }, follow_redirects=True)

    assert SiteSettings.get().sintegrum_api_base_url != 'http://api.sintegrum.com'


def test_interval_out_of_range_rejected(client, admin, settings):
    _login(client, admin)
    before = SiteSettings.get().sintegrum_sync_interval_minutes

    client.post('/admin/sintegrum/save', data={
        'base_url': 'https://api.sintegrum.com',
        'company_alias': 'multimededu',
        'sync_interval': '1',
        'access_ttl': '72',
    }, follow_redirects=True)

    assert SiteSettings.get().sintegrum_sync_interval_minutes == before


# ----------------------------- перевірка зв'язку -----------------------------

def test_connection_test_reports_success(client, admin, settings, monkeypatch):
    settings.sintegrum_api_key = 'k'
    db.session.flush()
    _login(client, admin)

    class _Resp:
        status_code = 200
        ok = True
        text = ''

        def json(self):
            return []

    monkeypatch.setattr(sc.requests, 'request', lambda *a, **kw: _Resp())
    body = client.post('/admin/sintegrum/test', follow_redirects=True).get_data(as_text=True)
    assert 'multimededu' in body


def test_connection_test_without_key_complains(client, admin, settings):
    settings.sintegrum_api_key = ''
    db.session.flush()
    _login(client, admin)

    response = client.post('/admin/sintegrum/test', follow_redirects=True)
    assert response.status_code == 200
    assert 'Заповніть' in response.get_data(as_text=True)


# ----------------------------- публікація курсу -----------------------------

def test_cannot_publish_without_price_and_link(client, admin, course):
    _login(client, admin)

    client.post(f'/admin/online-courses/{course.id}/publish', follow_redirects=True)

    db.session.refresh(course)
    assert course.is_published is False


def test_publish_works_when_ready(client, admin, course):
    course.price = Decimal('4500')
    course.access_url = 'https://multimededu.sintegrum.com/register/abc'
    db.session.flush()
    _login(client, admin)

    client.post(f'/admin/online-courses/{course.id}/publish', follow_redirects=True)

    db.session.refresh(course)
    assert course.is_published is True


def test_edit_form_cannot_publish_incomplete_course(client, admin, course):
    """Гейт стоїть на сервері, а не лише в шаблоні."""
    _login(client, admin)

    client.post(f'/admin/online-courses/{course.id}', data={
        'slug': course.slug,
        'price': '',
        'access_url': '',
        'is_published': 'on',
        'sort_order': '0',
    }, follow_redirects=True)

    db.session.refresh(course)
    assert course.is_published is False


def test_edit_saves_our_fields_only(client, admin, course):
    _login(client, admin)

    client.post(f'/admin/online-courses/{course.id}', data={
        'slug': course.slug,
        'title': 'Наша назва',
        'description': 'Наш опис',
        'short_description': 'Коротко',
        'price': '4500,50',
        'access_url': 'https://multimededu.sintegrum.com/register/abc',
        'duration_hours': '12',
        'sort_order': '3',
        'is_featured': 'on',
        'is_published': 'on',
    }, follow_redirects=True)

    db.session.refresh(course)
    assert course.title == 'Наша назва'
    assert course.price == Decimal('4500.50')  # кома як десятковий роздільник
    assert course.duration_hours == 12
    assert course.is_featured is True
    assert course.is_published is True
    # Дані Sintegrum форма не чіпає.
    assert course.remote_name == 'Плазмотерапія'


def test_edit_rejects_http_access_url(client, admin, course):
    _login(client, admin)

    client.post(f'/admin/online-courses/{course.id}', data={
        'slug': course.slug,
        'price': '4500',
        'access_url': 'http://insecure.example/register',
        'sort_order': '0',
    }, follow_redirects=True)

    db.session.refresh(course)
    assert course.access_url is None


def test_duplicate_slug_rejected(client, admin, course):
    other = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Інший', slug=f'oc-{uuid4().hex[:8]}',
    )
    db.session.add(other)
    db.session.flush()
    _login(client, admin)

    client.post(f'/admin/online-courses/{course.id}', data={
        'slug': other.slug,
        'price': '4500',
        'sort_order': '0',
    }, follow_redirects=True)

    db.session.refresh(course)
    assert course.slug != other.slug

    db.session.delete(other)
    db.session.flush()


def test_access_url_not_exposed_in_listing(client, admin, course):
    """Посилання -- фактично ключ від навчання; у списку показуємо лише ознаку."""
    course.price = Decimal('4500')
    course.access_url = 'https://multimededu.sintegrum.com/register/secret-token'
    db.session.flush()
    _login(client, admin)

    body = client.get('/admin/online-courses').get_data(as_text=True)
    assert 'secret-token' not in body


def test_listing_shows_every_course_including_vanished(client, admin, course):
    course.is_vanished = True
    db.session.flush()
    _login(client, admin)

    body = client.get('/admin/online-courses').get_data(as_text=True)
    assert 'Плазмотерапія' in body


# ----------------------------- хаб інтеграцій -----------------------------

def test_rotation_status_accepts_naive_datetime():
    """SQLite віддає DateTime(timezone=True) без tzinfo.

    Без нормалізації віднімання від aware-now кидало TypeError, і сторінка
    /admin/integrations падала в 500 через саму лише дату встановлення
    секрета -- для будь-якої інтеграції, не тільки Sintegrum.
    """
    from datetime import datetime, timedelta
    from app.admin._helpers import rotation_status

    naive = datetime.utcnow() - timedelta(days=10)
    result = rotation_status(naive, soft_days=365, hard_days=730)
    assert result['age_days'] == 10
    assert result['status'] == 'fresh'


def test_integrations_hub_shows_sintegrum_card(client, admin, settings):
    settings.sintegrum_api_key = 'k'
    db.session.flush()
    _login(client, admin)

    body = client.get('/admin/integrations').get_data(as_text=True)
    assert '/admin/sintegrum' in body
    assert 'k' in body  # сторінка не порожня
    assert 'Sintegrum' in body


def test_integrations_hub_survives_broken_rotation(client, admin, settings, monkeypatch):
    """Збійний статус однієї інтеграції не має класти всю сторінку."""
    import app.admin.routes_stubs as stubs

    def _boom(*args, **kwargs):
        raise ValueError('rotation broken')

    monkeypatch.setattr(stubs, 'rotation_status', _boom, raising=False)
    _login(client, admin)
    assert client.get('/admin/integrations').status_code == 200


def test_translations_survive_the_edit_form(client, admin, course):
    """Мовні вкладки зберігають переклади тим самим хелпером, що й решта
    адмін-форм: ручний цикл по мовах прибрано, тож регрес тут був би тихий."""
    _login(client, admin)
    # Ім'я інпута мовної вкладки: tr__<мова>__<поле> (routes_translations.inline_name).
    field_name = 'tr__ru__title'

    client.post(f'/admin/online-courses/{course.id}', data={
        'slug': course.slug,
        'title': 'Українська назва',
        'price': '4500',
        'sort_order': '0',
        field_name: 'Русское название',
    }, follow_redirects=True)

    db.session.refresh(course)
    assert course.title == 'Українська назва'
    assert (course.translations or {}).get('ru', {}).get('title') == 'Русское название'
