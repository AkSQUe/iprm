"""Партнерські події: реєстрації й надіслані листи в чергу доставок.

Досі назовні йшов лише каталог курсів. Партнер (MM Medic) веде картку тієї
самої людини, і без цих подій менеджер дзвонив із пропозицією рівно тоді,
коли ми написали їй утретє за тиждень.

Головна відмінність від каталожного вебхука — клас події. «Перечитай курс»
можна повторити скільки завгодно; реєстрацію чи надісланий лист — ні. Тому
тут ідемпотентний ``event_uuid``, підпис із часовою міткою й перевірка того,
що подія йде РІВНО НА ПЕРЕХОДІ стану, а не на кожному збереженні.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.models.webhook_delivery import WebhookDelivery


def _uid():
    return uuid4().hex[:8]


def _clear_partner_events():
    """Чистий старт: рядки черги переживають тест, і сусідній тест бачив би
    чужі події як свої."""
    WebhookDelivery.query.filter(
        WebhookDelivery.event_type.isnot(None)
    ).delete(synchronize_session=False)
    db.session.commit()


@pytest.fixture
def partner_on(app):
    _clear_partner_events()
    s = SiteSettings.get()
    s.partner_integration_enabled = True
    s.mm_medic_integration_enabled = True
    s.mm_medic_api_base_url = 'https://mm-medic.test'
    s.partner_webhook_secret = 'shared-secret-1234567890'
    db.session.commit()
    yield s
    s.partner_integration_enabled = False
    s.mm_medic_integration_enabled = False
    s.mm_medic_api_base_url = ''
    db.session.commit()
    _clear_partner_events()


@pytest.fixture
def registration(app):
    user = User(email=f'reg-{_uid()}@example.com', first_name='Тест',
                last_name='Учасник', email_confirmed=True, is_active=True)
    db.session.add(user)
    course = Course(title=f'Курс {_uid()}', slug=f'course-{_uid()}')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(course_id=course.id, location='Київ')
    db.session.add(instance)
    db.session.flush()

    row = EventRegistration(
        user_id=user.id, instance_id=instance.id,
        phone='+380501112233', specialty='Терапія', workplace='Клініка',
        status='pending', payment_status='unpaid',
    )
    db.session.add(row)
    db.session.commit()
    return row


def _events(event_type=None):
    query = WebhookDelivery.query.filter(WebhookDelivery.event_type.isnot(None))
    if event_type:
        query = query.filter_by(event_type=event_type)
    return query.all()


class TestRegistrationEvents:
    def test_new_registration_is_announced(self, app, partner_on, registration):
        rows = _events('registration.created')

        assert len(rows) == 1
        assert rows[0].payload['registration_id'] == registration.id
        assert rows[0].target_url.endswith('/api/partner/iprm/events')

    def test_payment_is_announced_once(self, app, partner_on, registration):
        """Подія має піти на ПЕРЕХОДІ, а не на кожному збереженні."""
        registration.payment_status = 'paid'
        db.session.commit()
        registration.workplace = 'Інша клініка'
        db.session.commit()

        assert len(_events('registration.paid')) == 1

    def test_cancellation_is_announced(self, app, partner_on, registration):
        registration.status = 'cancelled'
        db.session.commit()

        assert len(_events('registration.cancelled')) == 1

    def test_attendance_is_announced(self, app, partner_on, registration):
        registration.attended = True
        db.session.commit()

        assert len(_events('registration.attended')) == 1

    def test_payload_carries_what_the_partner_needs(self, app, partner_on,
                                                    registration):
        payload = _events('registration.created')[0].payload

        assert payload['iprm_user_id'] == registration.user_id
        assert payload['email']
        assert payload['course_slug']

    def test_starts_at_carries_the_date_of_the_event(self, app, partner_on,
                                                     registration):
        """Дата заходу читається з `start_date` -- так поле зветься в моделі.

        Роками payload віз `starts_at: null`: `_registration_payload` читав
        неіснуючий `instance.starts_at`, і партнер не бачив, коли саме
        людина вчиться.
        """
        registration.instance.start_date = datetime(
            2027, 3, 14, 9, 0, tzinfo=timezone.utc)
        registration.status = 'cancelled'
        db.session.commit()

        payload = _events('registration.cancelled')[0].payload

        assert payload['starts_at'] is not None
        assert payload['starts_at'].startswith('2027-03-14')

    def test_medical_details_do_not_leave(self, app, partner_on, registration):
        """Мінімізація видачі: ліцензія й стаж партнеру не потрібні."""
        payload = _events('registration.created')[0].payload

        assert 'license_number' not in payload
        assert 'experience_years' not in payload
        assert 'workplace' not in payload


class TestIntegrationOff:
    def test_nothing_is_queued_when_the_partner_is_off(self, app):
        settings = SiteSettings.get()
        settings.partner_integration_enabled = False
        db.session.commit()
        _clear_partner_events()

        user = User(email=f'off-{_uid()}@example.com', first_name='Т',
                    last_name='Т', email_confirmed=True, is_active=True)
        db.session.add(user)
        course = Course(title=f'Курс {_uid()}', slug=f'course-{_uid()}')
        db.session.add(course)
        db.session.flush()
        instance = CourseInstance(course_id=course.id, location='Київ')
        db.session.add(instance)
        db.session.flush()
        db.session.add(EventRegistration(
            user_id=user.id, instance_id=instance.id, phone='+380501112233',
            specialty='Терапія', workplace='Клініка',
        ))
        db.session.commit()

        assert _events() == []

    def test_missing_base_url_queues_nothing(self, app):
        _clear_partner_events()
        settings = SiteSettings.get()
        settings.partner_integration_enabled = True
        settings.mm_medic_integration_enabled = True
        settings.mm_medic_api_base_url = ''
        db.session.commit()

        from app.services.partner_events import emit

        assert emit('registration.created', {'registration_id': 1}) is None


class TestCommunicationEvents:
    def test_sent_letter_is_announced(self, app, partner_on):
        from app.models.email_log import EmailLog
        from app.services.partner_events import emit_communication_sent

        log = EmailLog(to_email='learner@example.com', subject='Тема',
                       template_name='registration_confirmed', status='sent',
                       trigger='registration')
        db.session.add(log)
        db.session.commit()

        emit_communication_sent(log)

        rows = _events('communication.sent')
        assert len(rows) == 1
        assert rows[0].payload['external_id'] == f'iprm-email-{log.id}'
        assert rows[0].payload['to_email'] == 'learner@example.com'

    def test_failed_letter_is_not_announced(self, app, partner_on):
        """Партнер має бачити дотик, а не нашу спробу дотику."""
        from app.models.email_log import EmailLog
        from app.services.partner_events import emit_communication_sent

        log = EmailLog(to_email='learner@example.com', subject='Тема',
                       template_name='registration_confirmed', status='failed',
                       trigger='registration')
        db.session.add(log)
        db.session.commit()

        emit_communication_sent(log)

        assert _events('communication.sent') == []

    def test_body_is_not_shipped(self, app, partner_on):
        from app.models.email_log import EmailLog
        from app.services.partner_events import emit_communication_sent

        log = EmailLog(to_email='learner@example.com', subject='Тема',
                       template_name='registration_confirmed', status='sent',
                       trigger='registration')
        db.session.add(log)
        db.session.commit()
        emit_communication_sent(log)

        payload = _events('communication.sent')[0].payload
        assert 'body' not in payload
        assert 'html' not in payload


class TestDeliveryShape:
    def test_partner_rows_are_distinguishable(self, app, partner_on, registration):
        row = _events('registration.created')[0]

        assert row.is_partner_event is True
        assert row.course_id is None
        assert row.status == 'pending'

    def test_event_uuid_is_unique_per_row(self, app, partner_on, registration):
        registration.payment_status = 'paid'
        db.session.commit()

        uuids = {row.event_uuid for row in _events()}
        assert len(uuids) == len(_events())
