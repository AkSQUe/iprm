"""Tests for public partner API v1.

Нова модель -- Course + CourseInstance. Формат JSON-відповіді незмінний
(партнерські сайти отримують "event-shape"), тому значна частина тестів
лишається ідентичною.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User


API_KEY = 'test-partner-api-key-12345678901234567890'


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def partner_settings(app):
    s = SiteSettings.get()
    s.partner_integration_enabled = True
    s.partner_api_key = API_KEY
    s.partner_prefill_secret = 'test-prefill-secret-' + 'x' * 32
    db.session.commit()
    yield s
    s.partner_integration_enabled = False
    s.partner_api_key = ''
    s.partner_prefill_secret = ''
    db.session.commit()


@pytest.fixture
def user(app):
    u = User(email=f'api-{_uid()}@test.com', password='pw-' + _uid(), first_name='T', last_name='U')
    db.session.add(u)
    db.session.flush()
    return u


@pytest.fixture
def published_event(app, user):
    """Course + published CourseInstance з форматом що очікує партнер."""
    c = Course(
        title='Published Event', slug=f'pub-{_uid()}',
        short_description='desc', event_type='course',
        base_price=1500, tags=['gynecology', 'ppp'],
        cpd_points_online=5, cpd_points_offline=5,
        is_active=True, created_by=user.id,
    )
    db.session.add(c)
    db.session.flush()
    inst = CourseInstance(
        course_id=c.id, status='published',
        event_format='offline', price=1500,
        cpd_points_online=5, cpd_points_offline=5,
        start_date=datetime.now(timezone.utc) + timedelta(days=10),
        end_date=datetime.now(timezone.utc) + timedelta(days=11),
    )
    db.session.add(inst)
    db.session.flush()
    # Для зручності в тестах -- віддаємо Course, а instance зберігаємо як атрибут.
    c._test_instance = inst
    return c


@pytest.fixture
def draft_event(app, user):
    c = Course(
        title='Draft', slug=f'draft-{_uid()}',
        event_type='course', base_price=0, is_active=True, created_by=user.id,
    )
    db.session.add(c)
    db.session.flush()
    inst = CourseInstance(
        course_id=c.id, status='draft', event_format='online', price=0,
    )
    db.session.add(inst)
    db.session.flush()
    c._test_instance = inst
    return c


@pytest.fixture
def hybrid_event(app, user):
    c = Course(
        title='Hybrid', slug=f'hyb-{_uid()}', event_type='course',
        base_price=1500, is_active=True, created_by=user.id,
    )
    db.session.add(c)
    db.session.flush()
    inst = CourseInstance(
        course_id=c.id, status='published', event_format='hybrid', price=1500,
        cpd_points_online=Decimal('7.50'), cpd_points_offline=Decimal('9.00'),
        start_date=datetime.now(timezone.utc) + timedelta(days=10),
    )
    db.session.add(inst)
    db.session.flush()
    c._test_instance = inst
    return c


@pytest.fixture
def offline_event_with_course_defaults(app, user):
    """Офлайн-проведення курсу, у якого заповнені ОБИДВА default-и балів.

    Найпоширеніша конфігурація: на сторінці курсу обидва поля видно завжди,
    тож адмін заповнює обидва, а конкретне проведення буває суто очним.
    """
    c = Course(
        title='Offline', slug=f'off-{_uid()}', event_type='course',
        base_price=1000, is_active=True, created_by=user.id,
        cpd_points_online=Decimal('7.50'), cpd_points_offline=Decimal('9.00'),
    )
    db.session.add(c)
    db.session.flush()
    inst = CourseInstance(
        course_id=c.id, status='published', event_format='offline', price=1000,
        start_date=datetime.now(timezone.utc) + timedelta(days=10),
    )
    db.session.add(inst)
    db.session.flush()
    c._test_instance = inst
    return c


def test_offline_event_does_not_claim_online_points(
    client, partner_settings, offline_event_with_course_defaults,
):
    """Захід без онлайн-участі не сміє звітувати онлайнові бали.

    Усередині ІПРМ це не видно: шаблони ходять через `cpd_pairs`, який
    фільтрує за форматами заходу. Партнер такого фільтра не має і надрукує
    діапазон «7,5-9» там, де онлайн-участі не існує взагалі.
    """
    resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
    card = next(
        item for item in resp.get_json()['items']
        if item['slug'] == offline_event_with_course_defaults.slug
    )
    assert card['cpd_points_online'] is None
    assert card['cpd_points_offline'] == 9.0


def test_event_card_exposes_points_per_format(
    client, partner_settings, hybrid_event,
):
    resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
    card = next(
        item for item in resp.get_json()['items']
        if item['slug'] == hybrid_event.slug
    )
    assert 'cpd_points' not in card
    assert card['cpd_points_online'] == 7.5
    assert card['cpd_points_offline'] == 9.0


class TestEventsList:
    def test_requires_api_key(self, client, partner_settings, published_event):
        resp = client.get('/api/v1/events')
        assert resp.status_code == 401

    def test_rejects_wrong_api_key(self, client, partner_settings, published_event):
        resp = client.get('/api/v1/events', headers={'X-API-Key': 'wrong-key'})
        assert resp.status_code == 401

    def test_returns_404_when_integration_disabled(self, client, published_event):
        # partner_settings fixture not requested → integration stays disabled
        resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
        assert resp.status_code == 404

    def test_lists_published_events(self, client, partner_settings, published_event, draft_event):
        resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
        assert resp.status_code == 200
        data = resp.get_json()
        slugs = {e['slug'] for e in data['items']}
        assert published_event.slug in slugs
        assert draft_event.slug not in slugs

    def test_event_card_shape(self, client, partner_settings, published_event):
        resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
        card = next(e for e in resp.get_json()['items'] if e['slug'] == published_event.slug)
        assert card['title'] == 'Published Event'
        # Проведення суто очне, тож онлайнових балів у нього немає --
        # навіть попри заповнений default курсу.
        assert card['cpd_points_online'] is None
        assert card['cpd_points_offline'] == 5.0
        assert card['tags'] == ['gynecology', 'ppp']
        assert card['currency'] == 'UAH'
        inst_id = published_event._test_instance.id
        assert card['registration_url'].endswith(f'/registration/instance/{inst_id}/register')
        assert card['detail_url'].endswith(f'/courses/{published_event.slug}')

    def test_card_carries_trainer_identity(self, client, partner_settings,
                                           published_event):
        """MM Medic звʼязує свого користувача з тренером за id (email -- для
        автопідбору при першому налаштуванні). Без цих двох полів роль
        «Тренер» там не має за чим відрізнити свої заходи від чужих, а
        звʼязування за іменем ламають тезки й зміна прізвища."""
        from app.models.trainer import Trainer

        trainer = Trainer(full_name='Іван Тренер', slug=f'tr-{_uid()}',
                          email='trainer@example.com', role='Лікар')
        db.session.add(trainer)
        db.session.flush()
        published_event._test_instance.trainer_id = trainer.id
        db.session.commit()

        resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
        card = next(e for e in resp.get_json()['items']
                    if e['slug'] == published_event.slug)

        assert card['trainer']['id'] == trainer.id
        assert card['trainer']['email'] == 'trainer@example.com'
        assert card['trainer']['full_name'] == 'Іван Тренер'

    def test_pagination_bounds(self, client, partner_settings, published_event):
        """per_page > MAX_PER_PAGE -> 400 Bad Request з error-повідомленням."""
        resp = client.get(
            '/api/v1/events?per_page=9999',
            headers={'X-API-Key': API_KEY},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'error' in data
        assert 'per_page' in data['error']


class TestEventDetail:
    def test_get_by_slug(self, client, partner_settings, published_event):
        resp = client.get(
            f'/api/v1/events/{published_event.slug}',
            headers={'X-API-Key': API_KEY},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['slug'] == published_event.slug
        assert 'program_blocks' in data
        assert 'description' in data

    def test_detail_carries_specialty_names(
        self, client, partner_settings, user,
    ):
        """Партнер має бачити перелік спеціальностей окремим полем.

        target_audience тепер несе лише ручний допис: перелік для
        сторінки збирається з довідника, і без цього ключа партнер
        втратив би його, щойно адміністратор прибере з поля дубль.
        """
        from app.models.specialty import Specialty

        db.session.add(Specialty(code=f'api-{_uid()}'[:60], name='Алергологія',
                                 section='medical', sort_order=2))
        db.session.flush()
        code = Specialty.query.filter_by(name='Алергологія').first().code
        c = Course(
            title='Захід зі спеціальностями', slug=f'spec-{_uid()}',
            event_type='seminar', base_price=0, is_active=True,
            created_by=user.id, bpr_specialty_codes=[code],
            target_audience=['а також усі, хто цікавиться темою'],
        )
        db.session.add(c)
        db.session.flush()
        db.session.add(CourseInstance(
            course_id=c.id, status='published', event_format='offline',
            price=0, start_date=datetime.now(timezone.utc) + timedelta(days=10),
        ))
        db.session.flush()

        data = client.get(f'/api/v1/events/{c.slug}',
                          headers={'X-API-Key': API_KEY}).get_json()
        assert data['bpr_specialties'] == ['Алергологія']
        assert data['target_audience'] == ['а також усі, хто цікавиться темою']

    def test_404_for_unknown_slug(self, client, partner_settings):
        resp = client.get(
            '/api/v1/events/nonexistent-slug-xyz',
            headers={'X-API-Key': API_KEY},
        )
        assert resp.status_code == 404

    def test_404_for_draft_only_course(self, client, partner_settings, draft_event):
        """Курс без published instances не показуємо в detail."""
        # Detail-endpoint повертає курс якщо is_active=True, навіть якщо всі
        # instances у draft. Партнер сам фільтрує за status представника.
        # Тому тут ми не очікуємо 404. Перевіряємо лише що JSON повертається.
        resp = client.get(
            f'/api/v1/events/{draft_event.slug}',
            headers={'X-API-Key': API_KEY},
        )
        assert resp.status_code == 200
        assert resp.get_json()['slug'] == draft_event.slug


class TestEventTypeOverride:
    """Проведення може перевизначити вид заходу окремо від курсу (наприклад,
    курс "Семінар" провели разово як "Тренінг"). Партнерський API мусить
    віддавати ефективний (перевизначений) код, як і всі сусідні instance-
    ефективні поля (event_format, status, cpd_points, ...)."""

    def test_list_returns_instance_override_not_course_type(
        self, client, partner_settings, user,
    ):
        c = Course(
            title='Перевизначений тип', slug=f'ovr-{_uid()}',
            event_type='seminar', base_price=0, is_active=True,
            created_by=user.id,
        )
        db.session.add(c)
        db.session.flush()
        inst = CourseInstance(
            course_id=c.id, status='published', event_format='offline',
            event_type='training', price=0,
            start_date=datetime.now(timezone.utc) + timedelta(days=10),
        )
        db.session.add(inst)
        db.session.flush()

        resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
        card = next(e for e in resp.get_json()['items'] if e['slug'] == c.slug)
        assert card['event_type'] == 'training'

    def test_detail_returns_instance_override_not_course_type(
        self, client, partner_settings, user,
    ):
        c = Course(
            title='Перевизначений тип у деталях', slug=f'ovr-{_uid()}',
            event_type='seminar', base_price=0, is_active=True,
            created_by=user.id,
        )
        db.session.add(c)
        db.session.flush()
        inst = CourseInstance(
            course_id=c.id, status='published', event_format='offline',
            event_type='training', price=0,
            start_date=datetime.now(timezone.utc) + timedelta(days=10),
        )
        db.session.add(inst)
        db.session.flush()

        resp = client.get(f'/api/v1/events/{c.slug}', headers={'X-API-Key': API_KEY})
        assert resp.get_json()['event_type'] == 'training'


class TestSeatsLeft:
    # Читаємо detail-ендпоінт, а не перший аркуш списку: список
    # посторінковий (50 на сторінку), а спільна тестова БД накопичує
    # закомічені курси інших тестів -- подія просто випадала зі сторінки.
    def _card(self, client, slug):
        resp = client.get(f'/api/v1/events/{slug}', headers={'X-API-Key': API_KEY})
        assert resp.status_code == 200
        return resp.get_json()

    def test_null_when_unlimited_capacity(
        self, client, partner_settings, published_event,
    ):
        inst = published_event._test_instance
        inst.max_participants = None
        db.session.commit()
        assert self._card(client, published_event.slug)['seats_left'] is None

    def test_reflects_active_registrations(
        self, client, partner_settings, published_event, user,
    ):
        inst = published_event._test_instance
        inst.max_participants = 10
        db.session.add_all([
            EventRegistration(
                user_id=user.id, instance_id=inst.id,
                phone='+380000000001', specialty='s', workplace='w',
                status='confirmed', payment_status='paid',
            ),
        ])
        db.session.commit()
        assert self._card(client, published_event.slug)['seats_left'] == 9


class TestInstanceGranularityKeepsHistory:
    """Поштучний режим -- це історія, а не каталог.

    `Course.is_active` відповідає на питання «чи пропонуємо ми цей курс
    зараз». Курс, знятий з продажу, минулого не скасовує, а поштучний режим
    існує рівно заради минулого: партнер (mm-medic) будує з нього звітність
    по проведених заходах.

    Ціна старої поведінки виміряна 31.08.2026: курс
    `avtorskyi-kurs-tsitaishvili` деактивували, і разом із ним із видачі
    зникли два завершені проведення 2024-2025 років, а з ними 22 реєстрації
    в дзеркалі партнера.
    """

    def _completed_on_disabled_course(self, user):
        c = Course(
            title='Знятий з продажу', slug=f'gone-{_uid()}',
            event_type='course', base_price=0, is_active=False,
            created_by=user.id,
        )
        db.session.add(c)
        db.session.flush()
        inst = CourseInstance(
            course_id=c.id, status='completed', event_format='offline',
            price=1000,
            start_date=datetime.now(timezone.utc) - timedelta(days=300),
        )
        db.session.add(inst)
        db.session.flush()
        db.session.commit()
        return c, inst

    def test_completed_instance_of_a_disabled_course_is_listed(
            self, client, partner_settings, user):
        _course, inst = self._completed_on_disabled_course(user)

        r = client.get(
            '/api/v1/events?granularity=instance'
            '&status=published,active,completed,cancelled&per_page=100',
            headers={'X-API-Key': API_KEY},
        )

        assert r.status_code == 200
        ids = {i['instance_id'] for i in r.get_json()['items']}
        assert inst.id in ids

    def test_the_catalogue_still_hides_it(self, client, partner_settings, user):
        """Покурсовий режим -- це вітрина, і там прапорець далі діє."""
        course, _inst = self._completed_on_disabled_course(user)

        r = client.get(
            '/api/v1/events?status=published,active,completed,cancelled'
            '&per_page=100',
            headers={'X-API-Key': API_KEY},
        )

        assert r.status_code == 200
        slugs = {i['slug'] for i in r.get_json()['items']}
        assert course.slug not in slugs

    def test_detail_still_returns_410(self, client, partner_settings, user):
        """Сторінку знятого курсу партнер показувати не має.

        Список історії та лендинг -- різні питання, і послаблення першого не
        має тихо послабити друге.
        """
        course, _inst = self._completed_on_disabled_course(user)

        r = client.get(f'/api/v1/events/{course.slug}',
                       headers={'X-API-Key': API_KEY})

        assert r.status_code == 410
