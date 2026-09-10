"""Шапка, hero і JSON-LD не повинні обіцяти те, чого немає в переліку дат.

Після пункту 7 блок дат показує лише відкриті проведення. Усе, що поруч
називає ціну, місця чи веде на реєстрацію, мусить рахуватися з ТОГО САМОГО
переліку -- інакше сторінка обіцяє «від 4 000» за дату, якої відвідувач у
списку не знайде.

Набрана група будується так само, як у test_course_schedule_block:
max_participants=1 плюс одна оплачена реєстрація.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from app.services.money import format_amount

EMAIL_PREFIX = 'hero-cons-'


@pytest.fixture(autouse=True)
def clean(app):
    def _wipe():
        stale = [u.id for u in User.query.filter(
            User.email.like(f'{EMAIL_PREFIX}%')).all()]
        if stale:
            EventRegistration.query.filter(
                EventRegistration.user_id.in_(stale)).delete(
                    synchronize_session=False)
            User.query.filter(User.id.in_(stale)).delete(
                synchronize_session=False)
        Course.query.filter(Course.slug.like('hero-cons%')).delete(
            synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


def _course(suffix, **kwargs):
    course = Course(
        slug=f'hero-cons{suffix}',
        title='Курс для перевірки шапки',
        is_active=True,
        description='<p>Повний опис курсу.</p>',
        **kwargs,
    )
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, *, days, price=None, max_participants=None):
    inst = CourseInstance(
        course_id=course.id,
        status='published',
        event_format='offline',
        location='Київ',
        start_date=datetime.now(timezone.utc) + timedelta(days=days),
        price=Decimal(price) if price is not None else None,
        max_participants=max_participants,
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _fill(inst, suffix):
    user = User(email=f'{EMAIL_PREFIX}{suffix}@test.com')
    db.session.add(user)
    db.session.flush()
    db.session.add(EventRegistration(
        user_id=user.id, instance_id=inst.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status='confirmed', payment_status='paid',
    ))


def test_hero_price_ignores_full_groups(client):
    """Ціна набраної групи не повинна ставати ціною курсу в hero."""
    course = _course('-price', base_price=Decimal('6000'))
    cheap_full = _instance(course, days=10, price='4000', max_participants=1)
    _fill(cheap_full, 'price')
    _instance(course, days=20, price='8000', max_participants=10)
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert format_amount(8000) in html
    assert format_amount(4000) not in html


def test_hero_price_falls_back_to_base_when_no_open_dates(client):
    """Жодної відкритої дати -> базова ціна курсу, а не ціна набраної групи."""
    course = _course('-fallback', base_price=Decimal('6000'))
    full = _instance(course, days=10, price='4000', max_participants=1)
    _fill(full, 'fallback')
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert format_amount(6000) in html
    assert format_amount(4000) not in html


def test_hero_cta_leads_to_request_when_no_open_dates(client):
    """Кнопка hero не повинна вести на блок, де показано порожній стан."""
    course = _course('-cta')
    full = _instance(course, days=10, max_participants=1)
    _fill(full, 'cta')
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    hero = html[html.find('iprm-hero__actions--detail'):]
    hero = hero[:hero.find('</div>')]
    assert 'href="#request"' in hero
    assert 'href="#schedule"' not in hero


def test_jsonld_reports_sold_out_when_no_open_dates(client):
    """Google не повинен обіцяти наявність, якої немає."""
    course = _course('-seo', base_price=Decimal('6000'))
    full = _instance(course, days=10, max_participants=1)
    _fill(full, 'seo')
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'schema.org/SoldOut' in html
    assert 'schema.org/InStock' not in html


def test_jsonld_reports_in_stock_when_a_date_is_open(client):
    course = _course('-seo-ok', base_price=Decimal('6000'))
    _instance(course, days=10, max_participants=10)
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'schema.org/InStock' in html
    assert 'schema.org/SoldOut' not in html


def test_header_seats_follow_the_nearest_open_date(client):
    """Лічильник у шапці -- про те саме проведення, що й чип у hero.

    Найближче відкрите -- без обмеження місць, тож числа немає взагалі.
    Показати «10» від пізнішої дати означало б приписати місткість не тому
    заходу.
    """
    course = _course('-seats')
    _instance(course, days=10, max_participants=None)
    _instance(course, days=20, max_participants=10)
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'iprm-header__seats' not in html


def test_lead_form_asks_for_a_request_when_no_open_dates(client):
    course = _course('-lead')
    full = _instance(course, days=10, max_participants=1)
    _fill(full, 'lead')
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'Залиште запит' in html
    # Саме заголовок форми, а не слово "надішлемо" взагалі: воно є ще й у
    # незмінному підзаголовку про спосіб зв'язку.
    assert 'Залиште контакт' not in html
