"""Місто проведення: окреме поле, пікер в адмінці, віддача партнеру.

Чому поле, а не розбір рядка. `course_instances.location` -- вільний текст, і
в проді одне й те саме місто записане трьома способами: "Київ", "м. Київ",
"Київ, вул. Андрія Верхогляда, 2а". Фасет «Місто» на партнерській вітрині за
таким рядком побудувати неможливо, а вгадувати місто з адреси означало б
помилятися мовчки (те саме рішення зафіксоване в app/services/city_glossary.py).

Місто НЕобов'язкове навмисно: у проді 86 зі 106 проведень не мають локації
взагалі, і розклад показує їх із підписом «Місце уточнюється» замість того,
щоб ховати захід.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text as sa_text

from app.extensions import db
from app.models.city import City
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.site_settings import SiteSettings
from app.models.user import User


API_KEY = 'test-partner-api-key-12345678901234567890'
HEADERS = {'X-API-Key': API_KEY}


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def partner_settings(app):
    s = SiteSettings.get()
    s.partner_integration_enabled = True
    s.partner_api_key = API_KEY
    db.session.commit()
    yield s
    s.partner_integration_enabled = False
    s.partner_api_key = ''
    db.session.commit()


@pytest.fixture
def author(app):
    u = User(email=f'city-{_uid()}@test.com', password='pw-' + _uid(),
             first_name='C', last_name='U')
    db.session.add(u)
    db.session.flush()
    return u


@pytest.fixture
def kyiv(app):
    city = City(name=f'Київ-{_uid()}')
    db.session.add(city)
    db.session.flush()
    return city


def _course_with_instance(author, *, city=None, location=None, days=800):
    course = Course(
        title='City course', slug=f'city-{_uid()}', short_description='d',
        event_type='course', base_price=100, is_active=True,
        created_by=author.id,
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        price=100, location=location,
        city_id=city.id if city else None,
        start_date=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.session.add(inst)
    db.session.flush()
    course._test_instance = inst
    return course


class TestPartnerPayload:
    def test_city_is_structured_not_parsed_from_address(
            self, client, partner_settings, author, kyiv):
        """Адреса лишається адресою, місто приходить окремим обʼєктом."""
        address = 'Київ, вул. Андрія Верхогляда, 2а'
        course = _course_with_instance(author, city=kyiv, location=address)
        db.session.commit()

        data = client.get('/api/v1/events?per_page=100', headers=HEADERS).get_json()
        card = next(i for i in data['items'] if i['slug'] == course.slug)

        assert card['location'] == address
        assert card['city'] == {'id': kyiv.id, 'name': kyiv.name}

    def test_city_is_null_when_venue_is_not_decided(
            self, client, partner_settings, author):
        """Місце ще не визначене -- партнер має відрізнити це від помилки."""
        course = _course_with_instance(author, city=None, location=None)
        db.session.commit()

        data = client.get('/api/v1/events?per_page=100', headers=HEADERS).get_json()
        card = next(i for i in data['items'] if i['slug'] == course.slug)

        assert card['city'] is None
        assert card['location'] is None

    def test_same_city_for_differently_written_addresses(
            self, client, partner_settings, author, kyiv):
        """Головне, заради чого поле й заводилось: три написання -- одне місто.

        Саме тут фасет за рядком `location` розсипався б на три різні
        «міста», і фільтр показував би третину заходів замість усіх.
        """
        written = ['Київ', 'м. Київ', 'Київ, вул. Андрія Верхогляда, 2а']
        slugs = {
            _course_with_instance(author, city=kyiv, location=text).slug
            for text in written
        }
        db.session.commit()

        data = client.get('/api/v1/events?per_page=100', headers=HEADERS).get_json()
        cards = [i for i in data['items'] if i['slug'] in slugs]

        assert len(cards) == 3
        assert {c['city']['id'] for c in cards} == {kyiv.id}
        assert {c['location'] for c in cards} == set(written)

    def test_city_present_in_detail_instances(
            self, client, partner_settings, author, kyiv):
        course = _course_with_instance(author, city=kyiv, location='Київ')
        db.session.commit()

        data = client.get(f'/api/v1/events/{course.slug}', headers=HEADERS).get_json()
        assert data['instances'][0]['city'] == {'id': kyiv.id, 'name': kyiv.name}


class TestAdminPicker:
    """Поле, яке нікому нема чим заповнити, лишається порожнім назавжди."""

    def test_form_offers_cities_and_an_undecided_option(self, app, kyiv):
        from app.admin.forms import CourseInstanceForm
        from app.admin.routes_instances import _populate_choices

        db.session.commit()
        with app.test_request_context():
            form = CourseInstanceForm()
            _populate_choices(form)

        labels = dict(form.city_id.choices)
        assert labels[0] == '--- Місце уточнюється ---'
        assert labels[kyiv.id] == kyiv.name

    def test_undecided_is_saved_as_null_not_zero(self, app, author, kyiv):
        """0 -- це мітка «не обрано» в пікері, а не id міста."""
        from app.admin.forms import CourseInstanceForm
        from app.services import course_service

        course = _course_with_instance(author, city=kyiv)
        instance = course._test_instance
        db.session.commit()

        with app.test_request_context():
            form = CourseInstanceForm(obj=instance)
            form.city_id.data = 0
            course_service.populate_instance_from_form(instance, form)

        assert instance.city_id is None

    def test_picked_city_is_stored(self, app, author, kyiv):
        from app.admin.forms import CourseInstanceForm
        from app.services import course_service

        course = _course_with_instance(author, city=None)
        instance = course._test_instance
        db.session.commit()

        with app.test_request_context():
            form = CourseInstanceForm(obj=instance)
            form.city_id.data = kyiv.id
            course_service.populate_instance_from_form(instance, form)

        assert instance.city_id == kyiv.id


class TestCityDeletion:
    def test_deleting_a_city_does_not_delete_the_event(self, app, author, kyiv):
        """ondelete=SET NULL: місто -- довідник, а не власник проведення.

        CASCADE тут знищив би заходи разом із рядком довідника, і зробив би це
        мовчки — при спробі почистити список міст в адмінці.
        """
        course = _course_with_instance(author, city=kyiv)
        instance_id = course._test_instance.id
        db.session.commit()

        # SQLite не застосовує ON DELETE, доки не ввімкнена прагма (PostgreSQL
        # застосовує завжди). Без цього тест перевіряв би не поведінку СУБД, а
        # те, що рядок просто лишився на місці — і мовчав би про CASCADE.
        if db.engine.dialect.name == 'sqlite':
            db.session.execute(sa_text('PRAGMA foreign_keys=ON'))

        db.session.delete(kyiv)
        db.session.commit()

        survivor = db.session.get(CourseInstance, instance_id)
        assert survivor is not None
        assert survivor.city_id is None
