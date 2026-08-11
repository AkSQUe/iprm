"""Партнерське API: учасники, реєстрації, ліди.

Це те, чого бракувало для єдиної бази клієнтів: назовні віддавалися лише
заходи, тож картка учасника для партнера не існувала взагалі.

Тести стережуть чотири речі, кожна з яких ламається тихо:
  * авторизація -- ендпоінти віддають персональні дані, тож без ключа не
    мають повертати нічого, а при вимкненій інтеграції -- навіть не
    зізнаватися, що існують;
  * курсор `updated_since` -- без нього партнер щопівгодини тягне всю базу
    й однаково не знає, що змінилось;
  * канонічний телефон -- головний ключ зіставлення; непізнаний номер має
    приходити порожнім, а не вгаданим;
  * ліди двох різних типів в одному потоці з правильною загальною
    кількістю: пагінація тут іде ПІСЛЯ обʼєднання.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.b2b_request import B2BRequest
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_request import CourseRequest
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
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


def _user(phone='+380671112233', email=None):
    user = User(email=email or f'p-{_uid()}@test.com', password='pw-' + _uid(),
                first_name='Іван', last_name='Петренко')
    db.session.add(user)
    db.session.flush()
    profile = MedicalProfile.query.get(user.id)
    if profile is None:
        profile = MedicalProfile(user_id=user.id)
        db.session.add(profile)
    profile.phone = phone
    profile.participant_type = 'doctor'
    profile.workplace = 'Клініка'
    db.session.commit()
    return user


class TestAuth:
    def test_participants_require_a_key(self, client, partner_settings):
        assert client.get('/api/v1/participants').status_code == 401

    def test_registrations_require_a_key(self, client, partner_settings):
        assert client.get('/api/v1/registrations').status_code == 401

    def test_leads_require_a_key(self, client, partner_settings):
        assert client.get('/api/v1/leads').status_code == 401

    def test_disabled_integration_hides_existence(self, client):
        """404, а не 401: вимкнена інтеграція не має підтверджувати, що
        ендпоінт узагалі є."""
        assert client.get('/api/v1/participants', headers=HEADERS).status_code == 404


class TestParticipants:
    def test_returns_canonical_phone(self, client, partner_settings):
        user = _user(phone='0671112233')
        db.session.commit()

        data = client.get('/api/v1/participants?per_page=200',
                          headers=HEADERS).get_json()
        row = next(i for i in data['items'] if i['id'] == user.id)

        assert row['phone_e164'] == '+380671112233'
        assert row['phone_raw'] == '0671112233'

    def test_unparsable_phone_comes_back_empty_not_guessed(
            self, client, partner_settings):
        """Вигадана канонічна форма зшила б не тих людей."""
        user = _user(phone='+3806784014070730886')
        db.session.commit()

        data = client.get('/api/v1/participants?per_page=200',
                          headers=HEADERS).get_json()
        row = next(i for i in data['items'] if i['id'] == user.id)

        assert row['phone_e164'] is None
        assert row['phone_raw'] == '+3806784014070730886'

    def test_profile_fields_are_present(self, client, partner_settings):
        user = _user()
        db.session.commit()

        data = client.get('/api/v1/participants?per_page=200',
                          headers=HEADERS).get_json()
        row = next(i for i in data['items'] if i['id'] == user.id)

        assert row['participant_type'] == 'doctor'
        assert row['workplace'] == 'Клініка'
        assert row['email'] == user.email


class TestCursor:
    def test_updated_since_excludes_older_rows(self, client, partner_settings):
        """Без курсора партнер тягнув би всю базу на кожен прогін."""
        old = _user()
        old.updated_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.session.commit()

        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        data = client.get(f'/api/v1/participants?per_page=200&updated_since={cutoff}',
                          headers=HEADERS).get_json()

        assert old.id not in {i['id'] for i in data['items']}

    def test_rows_are_ordered_by_change_time(self, client, partner_settings):
        """Будь-який інший порядок робить курсор марним: сторінка 2 могла б
        містити старіші зміни за сторінку 1."""
        for _ in range(3):
            _user()
        db.session.commit()

        data = client.get('/api/v1/participants?per_page=200',
                          headers=HEADERS).get_json()
        stamps = [i['updated_at'] for i in data['items'] if i['updated_at']]

        assert stamps == sorted(stamps)

    def test_bad_cursor_is_rejected(self, client, partner_settings):
        resp = client.get('/api/v1/participants?updated_since=вчора', headers=HEADERS)
        assert resp.status_code == 400


class TestRegistrations:
    def test_returns_payment_and_attendance(self, client, partner_settings):
        user = _user()
        course = Course(title='Курс', slug=f'c-{_uid()}', event_type='course',
                        base_price=1000, is_active=True, created_by=user.id)
        db.session.add(course)
        db.session.flush()
        inst = CourseInstance(course_id=course.id, status='published',
                              event_format='offline', price=1000,
                              start_date=datetime.now(timezone.utc) + timedelta(days=5))
        db.session.add(inst)
        db.session.flush()
        db.session.add(EventRegistration(
            user_id=user.id, instance_id=inst.id, phone='+380671112233',
            specialty='Гінекологія', workplace='Клініка',
            status='confirmed', payment_status='paid', attended=True,
        ))
        db.session.commit()

        data = client.get('/api/v1/registrations?per_page=200',
                          headers=HEADERS).get_json()
        row = next(i for i in data['items'] if i['user_id'] == user.id)

        assert row['status'] == 'confirmed'
        assert row['payment_status'] == 'paid'
        assert row['attended'] is True
        assert row['course_slug'] == course.slug
        # Знімок анкети на момент реєстрації, а не поточний профіль.
        assert row['specialty'] == 'Гінекологія'

    def test_participant_identity_is_included(self, client, partner_settings):
        """Ім'я й пошта живуть на картці, а не в реєстрації.

        Без них партнер отримує рядок без жодної ознаки, КОГО він показує --
        саме так у його адмінці й вийшов список із порожньою колонкою
        учасника при 1069 рядках.
        """
        user = _user()
        course = Course(title='Курс', slug=f'c-{_uid()}', event_type='course',
                        base_price=1000, is_active=True, created_by=user.id)
        db.session.add(course)
        db.session.flush()
        inst = CourseInstance(course_id=course.id, status='published',
                              event_format='offline', price=1000,
                              start_date=datetime.now(timezone.utc) + timedelta(days=5))
        db.session.add(inst)
        db.session.flush()
        db.session.add(EventRegistration(
            user_id=user.id, instance_id=inst.id, phone='+380671112233',
            specialty='Гінекологія', workplace='Клініка',
        ))
        db.session.commit()

        data = client.get('/api/v1/registrations?per_page=200',
                          headers=HEADERS).get_json()
        row = next(i for i in data['items'] if i['user_id'] == user.id)

        assert row['first_name'] == 'Іван'
        assert row['last_name'] == 'Петренко'
        assert row['email'] == user.email
        assert row['phone_e164'] == '+380671112233'


class TestLeads:
    def test_two_sources_in_one_stream(self, client, partner_settings):
        """Для менеджера це один список «хтось залишив контакти»."""
        db.session.add(B2BRequest(
            first_name='Ольга', last_name='К', phone='+380671112233',
            email=f'b2b-{_uid()}@test.com', team_size='6-10',
        ))
        user = _user()
        course = Course(title='Курс', slug=f'c-{_uid()}', event_type='course',
                        base_price=1000, is_active=True, created_by=user.id)
        db.session.add(course)
        db.session.flush()
        db.session.add(CourseRequest(
            course_id=course.id, email=f'req-{_uid()}@test.com',
            phone='+380671112244', message='Проведіть у Львові',
        ))
        db.session.commit()

        data = client.get('/api/v1/leads?per_page=200', headers=HEADERS).get_json()
        kinds = {i['kind'] for i in data['items']}

        assert 'b2b' in kinds
        assert 'course_request' in kinds

    def test_total_counts_both_sources(self, client, partner_settings):
        """Пагінація йде ПІСЛЯ обʼєднання, тож total -- спільний, а не сума
        двох незалежних вибірок."""
        db.session.add(B2BRequest(
            first_name='А', last_name='Б', phone='+380670000001',
            email=f'b2b-{_uid()}@test.com', team_size='3-5',
        ))
        db.session.commit()

        data = client.get('/api/v1/leads?per_page=1', headers=HEADERS).get_json()

        assert data['total'] >= 1
        assert len(data['items']) <= 1
        assert data['pages'] >= 1

    def test_ids_do_not_collide_between_sources(self, client, partner_settings):
        """`b2b-1` і `course-1` -- різні заявки; голий id їх злив би."""
        data = client.get('/api/v1/leads?per_page=200', headers=HEADERS).get_json()
        ids = [i['id'] for i in data['items']]

        assert len(ids) == len(set(ids))
        assert all(i.startswith(('b2b-', 'course-')) for i in ids)


class TestPrivacyHeaders:
    def test_personal_data_is_not_cacheable(self, client, partner_settings):
        """Каталог заходів кешується публічно; ці відповіді -- про конкретних
        людей, і проксі не має тримати їх у себе."""
        resp = client.get('/api/v1/participants', headers=HEADERS)

        assert resp.headers.get('Cache-Control') == 'no-store'
