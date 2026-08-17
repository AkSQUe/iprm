"""Партнерський ендпоінт каталогу онлайн-курсів (для MM Medic).

Найважливіше тут -- те, чого у відповіді бути НЕ повинно: посилання на
навчання і внутрішній ідентифікатор Sintegrum. Окремий тест звіряє набір
полів із білим списком, тож нове поле моделі не поїде партнеру мовчки.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.api.v1.serializers import ONLINE_COURSE_PUBLIC_FIELDS
from app.extensions import db
from app.models.online_course import OnlineCourse
from app.models.site_settings import SiteSettings

API_KEY = 'partner-key-for-tests'
ACCESS_URL = 'https://multimededu.sintegrum.com/register/secret-xyz'


@pytest.fixture(autouse=True)
def partner_enabled(app):
    settings = SiteSettings.get()
    settings.partner_integration_enabled = True
    settings.partner_api_key = API_KEY
    OnlineCourse.query.delete()
    db.session.commit()
    yield settings
    OnlineCourse.query.delete()
    db.session.commit()


def _course(published=True, **kwargs):
    kwargs.setdefault('remote_name', 'Плазмотерапія')
    kwargs.setdefault('remote_description', 'Опис із Sintegrum')
    kwargs.setdefault('price', Decimal('4500'))
    kwargs.setdefault('access_url', ACCESS_URL)
    course = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        slug=f'api-{uuid4().hex[:8]}',
        is_published=published,
        **kwargs,
    )
    db.session.add(course)
    db.session.commit()
    return course


def _get(client, url='/api/v1/online-courses', key=API_KEY):
    headers = {'X-API-Key': key} if key else {}
    return client.get(url, headers=headers)


# ----------------------------- автентифікація -----------------------------

def test_requires_api_key(client):
    _course()
    assert _get(client, key=None).status_code == 401


def test_rejects_wrong_key(client):
    _course()
    assert _get(client, key='nope').status_code == 401


def test_disabled_integration_hides_endpoint(client, partner_enabled):
    partner_enabled.partner_integration_enabled = False
    db.session.commit()
    assert _get(client).status_code == 404


# ----------------------------- видача -----------------------------

def test_returns_published_courses(client):
    course = _course()
    payload = _get(client).get_json()

    assert payload['total'] == 1
    assert payload['items'][0]['slug'] == course.slug


def test_unpublished_and_vanished_are_hidden(client):
    _course(published=True)
    _course(published=False)
    _course(published=True, is_vanished=True)

    payload = _get(client).get_json()
    assert payload['total'] == 1


def test_public_url_points_to_iprm_page(client):
    course = _course()
    item = _get(client).get_json()['items'][0]
    assert item['public_url'].endswith(f'/online-courses/{course.slug}')


def test_our_price_is_exposed_not_remote(client):
    _course(price=Decimal('6000'), remote_price=Decimal('1234'))
    item = _get(client).get_json()['items'][0]
    assert item['price'] == 6000.0


# ----------------------------- що не віддаємо -----------------------------

def test_access_url_never_leaves_iprm(client):
    _course()
    response = _get(client)
    assert 'secret-xyz' not in response.get_data(as_text=True)
    assert 'access_url' not in response.get_json()['items'][0]


def test_sintegrum_id_is_not_exposed(client):
    course = _course()
    item = _get(client).get_json()['items'][0]
    assert 'sintegrum_id' not in item
    assert str(course.sintegrum_id) not in str(item)


def test_response_fields_match_the_whitelist(client):
    """Падає, щойно хтось додасть поле в серіалізатор наосліп."""
    _course()
    item = _get(client).get_json()['items'][0]
    assert set(item) == set(ONLINE_COURSE_PUBLIC_FIELDS)


# ----------------------------- параметри -----------------------------

def test_pagination(client):
    for _ in range(3):
        _course()

    payload = _get(client, '/api/v1/online-courses?per_page=2').get_json()
    assert len(payload['items']) == 2
    assert payload['total'] == 3
    assert payload['pages'] == 2


def test_invalid_pagination_is_400(client):
    assert _get(client, '/api/v1/online-courses?per_page=999').status_code == 400
    assert _get(client, '/api/v1/online-courses?page=abc').status_code == 400


def test_updated_since_filters(client):
    from datetime import timedelta
    from app.models.mixins import utcnow

    course = _course()
    future = (utcnow() + timedelta(days=1)).isoformat()
    payload = _get(
        client, f'/api/v1/online-courses?updated_since={future}',
    ).get_json()
    assert payload['total'] == 0

    past = (utcnow() - timedelta(days=1)).isoformat()
    payload = _get(client, f'/api/v1/online-courses?updated_since={past}').get_json()
    assert payload['total'] == 1
    assert payload['items'][0]['slug'] == course.slug


def test_invalid_updated_since_is_400(client):
    assert _get(
        client, '/api/v1/online-courses?updated_since=not-a-date',
    ).status_code == 400


def test_lang_switches_texts(client):
    course = _course(title='Українська назва')
    course.set_translation('ru', 'title', 'Русское название')
    db.session.commit()

    uk = _get(client, '/api/v1/online-courses?lang=uk').get_json()['items'][0]
    ru = _get(client, '/api/v1/online-courses?lang=ru').get_json()['items'][0]

    assert uk['title'] == 'Українська назва'
    assert ru['title'] == 'Русское название'


def test_invalid_lang_is_400(client):
    assert _get(client, '/api/v1/online-courses?lang=de').status_code == 400


def test_response_is_cacheable(client):
    _course()
    response = _get(client)
    assert 'max-age' in response.headers.get('Cache-Control', '')


def test_updated_since_survives_unencoded_plus(client):
    """'+' у query-рядку декодується як пробіл -- зсув має відновлюватись.

    Партнер, що передав коректний ISO-час із зсувом, не має отримувати 400
    лише через правила кодування URL.
    """
    course = _course()
    response = _get(
        client, '/api/v1/online-courses?updated_since=2000-01-01T00:00:00 00:00',
    )
    assert response.status_code == 200
    assert response.get_json()['items'][0]['slug'] == course.slug


def test_updated_since_accepts_z_suffix(client):
    _course()
    response = _get(
        client, '/api/v1/online-courses?updated_since=2000-01-01T00:00:00Z',
    )
    assert response.status_code == 200
    assert response.get_json()['total'] == 1
