"""Публічний каталог онлайн-курсів і сторінка курсу.

Ключове, що перевіряється: на публіку не потрапляє нічого, крім
опублікованих курсів, і посилання на навчання не витікає в HTML.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.online_course import OnlineCourse
from app.models.site_settings import SiteSettings

ACCESS_URL = 'https://multimededu.sintegrum.com/register/secret-token-xyz'


def _course(published=True, **kwargs):
    kwargs.setdefault('remote_name', 'Плазмотерапія в косметології')
    kwargs.setdefault('price', Decimal('4500'))
    kwargs.setdefault('access_url', ACCESS_URL)
    course = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        slug=f'oc-{uuid4().hex[:8]}',
        is_published=published,
        **kwargs,
    )
    db.session.add(course)
    db.session.flush()
    return course


@pytest.fixture(autouse=True)
def clean_catalog(app):
    """Каталог спільний для всіх тестів набору -- прибираємо за собою.

    Саме commit, а не flush: після HTTP-запиту Flask-SQLAlchemy скидає
    сесію, і рядки, створені до запиту, переживають відкат тестової
    транзакції. Без цього наступний тест бачив би чужі курси -- і
    перевірка порожнього каталогу падала б через сусіда.
    """
    OnlineCourse.query.delete()
    db.session.commit()
    yield
    OnlineCourse.query.delete()
    db.session.commit()


# ----------------------------- каталог -----------------------------

def test_catalog_renders(client):
    course = _course()
    body = client.get('/online-courses/').get_data(as_text=True)
    assert course.remote_name in body


def test_catalog_shows_only_published(client):
    visible = _course(published=True, remote_name='Видимий курс')
    hidden = _course(published=False, remote_name='Прихований курс')

    body = client.get('/online-courses/').get_data(as_text=True)
    assert visible.remote_name in body
    assert hidden.remote_name not in body


def test_catalog_hides_vanished(client):
    course = _course(remote_name='Зниклий курс', is_vanished=True)
    body = client.get('/online-courses/').get_data(as_text=True)
    assert course.remote_name not in body


def test_catalog_empty_state(client):
    body = client.get('/online-courses/').get_data(as_text=True)
    assert 'скоро' in body.lower()


def test_featured_course_comes_first(client):
    _course(remote_name='Звичайний', sort_order=1)
    _course(remote_name='Закріплений', sort_order=9, is_featured=True)

    body = client.get('/online-courses/').get_data(as_text=True)
    assert body.index('Закріплений') < body.index('Звичайний')


# ----------------------------- сторінка курсу -----------------------------

def test_detail_renders(client):
    course = _course(short_description='Коротко про курс')
    body = client.get(f'/online-courses/{course.slug}').get_data(as_text=True)

    assert course.remote_name in body
    assert 'Коротко про курс' in body
    assert '4500' in body


def test_detail_of_unpublished_is_404(client):
    course = _course(published=False)
    assert client.get(f'/online-courses/{course.slug}').status_code == 404


def test_detail_of_vanished_is_404(client):
    course = _course(is_vanished=True)
    assert client.get(f'/online-courses/{course.slug}').status_code == 404


def test_unknown_slug_is_404(client):
    assert client.get('/online-courses/no-such-course').status_code == 404


def test_our_title_overrides_remote(client):
    course = _course(title='Наша назва курсу')
    body = client.get(f'/online-courses/{course.slug}').get_data(as_text=True)
    assert 'Наша назва курсу' in body


def test_our_price_is_shown_not_remote(client):
    """remote_price -- довідкове поле і в продаж не потрапляє (рішення Q3)."""
    course = _course(price=Decimal('6000'), remote_price=Decimal('1234'))
    body = client.get(f'/online-courses/{course.slug}').get_data(as_text=True)

    assert '6000' in body
    assert '1234' not in body


# ----------------------------- витік посилання -----------------------------

def test_access_url_never_reaches_catalog_html(client):
    _course()
    body = client.get('/online-courses/').get_data(as_text=True)
    assert 'secret-token-xyz' not in body


def test_access_url_never_reaches_detail_html(client):
    course = _course()
    body = client.get(f'/online-courses/{course.slug}').get_data(as_text=True)
    assert 'secret-token-xyz' not in body


# ----------------------------- SEO -----------------------------

def test_detail_has_course_jsonld(client):
    course = _course()
    body = client.get(f'/online-courses/{course.slug}').get_data(as_text=True)

    assert '"@type": "Course"' in body
    # Саме Course, а не Event: дат проведення в онлайн-курсу немає.
    assert '"@type": "Event"' not in body
    assert '"priceCurrency": "UAH"' in body


def test_detail_has_canonical(client):
    course = _course()
    body = client.get(f'/online-courses/{course.slug}').get_data(as_text=True)
    assert f'/online-courses/{course.slug}' in body


def test_sitemap_lists_published_courses(client):
    visible = _course(published=True)
    hidden = _course(published=False)

    body = client.get('/sitemap.xml').get_data(as_text=True)
    assert f'/online-courses/{visible.slug}' in body
    assert f'/online-courses/{hidden.slug}' not in body


# ----------------------------- навігація -----------------------------

def test_nav_link_hidden_until_enabled(client):
    _course()
    settings = SiteSettings.get()
    settings.show_online_courses = False
    db.session.flush()

    body = client.get('/').get_data(as_text=True)
    assert 'href="/online-courses/"' not in body


def test_nav_link_appears_when_enabled(client):
    _course()
    settings = SiteSettings.get()
    settings.show_online_courses = True
    db.session.flush()

    body = client.get('/').get_data(as_text=True)
    assert '/online-courses/' in body

    settings.show_online_courses = False
    db.session.flush()


# ----------------------------- відсутність inline -----------------------------

def test_pages_have_no_inline_styles(client):
    course = _course()
    for url in ('/online-courses/', f'/online-courses/{course.slug}'):
        body = client.get(url).get_data(as_text=True)
        assert 'style="' not in body, url


def test_jsonld_survives_quotes_in_the_title(client):
    """Розмітка збирається dict-ом і йде через tojson.

    Раніше назви хлібних крихт вставлялись у лапках вручну, тож лапка в
    назві курсу зробила б блок невалідним JSON -- і Google мовчки викинув би
    сторінку з розширеної видачі.
    """
    import json
    import re

    course = _course(remote_name='Курс "Плазма" й апостроф')
    body = client.get(f'/online-courses/{course.slug}').get_data(as_text=True)

    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', body, re.S)
    parsed = [json.loads(block) for block in blocks]

    types = {item.get('@type') for item in parsed}
    assert 'Course' in types and 'BreadcrumbList' in types
    course_schema = next(i for i in parsed if i.get('@type') == 'Course')
    assert course_schema['name'] == 'Курс "Плазма" й апостроф'
    assert course_schema['inLanguage']


def test_catalog_has_own_og_image(client):
    _course()
    body = client.get('/online-courses/').get_data(as_text=True)
    assert 'og-logo-simple.png' in body
