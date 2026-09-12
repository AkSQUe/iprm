"""Дії «Перевидати сертифікат» в адмінці (учасник і лектор).

Перевидача -- окрема кнопка, а не поведінка «Переслати»: вона міняє номер,
який уже названо людині. Ці тести стережуть саме цю межу -- що пересилання
лишається пересиланням, а перевидача доходить до документа й до листа.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.models.user import User
from app.services import certificate_service
from tests.support.rbac import make_super_admin


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin_client(client):
    user = make_super_admin(email=f'reis-adm-{_uid()}@test.com')
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    return client


@pytest.fixture
def no_pdf(monkeypatch):
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')
    monkeypatch.setattr(certificate_service, '_discard_stale_pdf',
                        lambda path, keep=None: None)


@pytest.fixture
def no_email(monkeypatch):
    """Пошта в тестах не йде; що її звали -- видно зі списку sent."""
    sent = []
    from app.services.email_service import EmailService
    monkeypatch.setattr(EmailService, 'send_certificate',
                        staticmethod(lambda cert: sent.append(cert.number)))
    return sent


@pytest.fixture
def registration(app):
    SiteSettings.get().bpr_provider_number = '2738'
    course = Course(title='Курс', slug=f'reisr-{_uid()}', is_active=True,
                    cpd_points_online=12, cpd_points_offline=12,
                    bpr_event_number='1028974', bpr_lecturer_points=5)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ',
        start_date=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db.session.add(instance)
    db.session.flush()
    user = User.create_with_password(
        f'reisr-{_uid()}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='completed',
        payment_status='paid', attended=True)
    db.session.add(reg)
    db.session.commit()
    return reg


def _event_segment(number):
    return number.split('-')[2]


class TestParticipant:
    def test_reissue_prints_the_corrected_number(self, admin_client, registration,
                                                 no_pdf, no_email):
        cert = certificate_service.issue_certificate(registration)
        assert _event_segment(cert.number) == '1028974'
        registration.instance.bpr_event_number = '1031500'
        db.session.commit()

        response = admin_client.post(
            f'/admin/registrations/{registration.id}/certificate/reissue',
            follow_redirects=True)

        assert response.status_code == 200
        assert _event_segment(registration.certificate.number) == '1031500'

    def test_reissue_sends_the_updated_certificate(self, admin_client, registration,
                                                   no_pdf, no_email):
        certificate_service.issue_certificate(registration)
        registration.instance.bpr_event_number = '1031500'
        db.session.commit()

        admin_client.post(
            f'/admin/registrations/{registration.id}/certificate/reissue',
            follow_redirects=True)

        assert no_email == [registration.certificate.number]

    def test_resend_leaves_the_number_alone(self, admin_client, registration,
                                            no_pdf, no_email):
        """Межа фічі: пересилання не має тихо перевидавати документ."""
        issued = certificate_service.issue_certificate(registration).number
        registration.instance.bpr_event_number = '1031500'
        db.session.commit()

        admin_client.post(
            f'/admin/registrations/{registration.id}/certificate/resend',
            follow_redirects=True)

        assert registration.certificate.number == issued

    def test_reissue_without_certificate_is_refused(self, admin_client,
                                                    registration, no_pdf, no_email):
        response = admin_client.post(
            f'/admin/registrations/{registration.id}/certificate/reissue',
            follow_redirects=True)

        assert response.status_code == 200
        assert 'Сертифікат не знайдено' in response.get_data(as_text=True)

    def test_reissue_needs_the_permission(self, client, registration, no_pdf,
                                          no_email):
        certificate_service.issue_certificate(registration)
        viewer = User.create_with_password(
            f'reis-view-{_uid()}@test.com', 'password123',
            first_name='В', last_name='Ю', email_confirmed=True)
        db.session.commit()
        with client.session_transaction() as session:
            session['_user_id'] = str(viewer.id)

        response = client.post(
            f'/admin/registrations/{registration.id}/certificate/reissue')

        assert response.status_code in (302, 403)


class TestLecturer:
    @pytest.fixture
    def instance(self, registration):
        from app.services import trainer_links

        trainer = Trainer(full_name='Тренер Тренерович',
                          full_name_dative='Тренеру Тренеровичу',
                          slug=f'trainer-{_uid()}')
        db.session.add(trainer)
        db.session.flush()
        instance = registration.instance
        trainer_links.set_trainers(instance, [trainer.id])
        db.session.commit()
        return instance, trainer

    @pytest.fixture
    def no_render(self, monkeypatch):
        monkeypatch.setattr(certificate_service, 'render_lecturer_pdf',
                            lambda lc, font_config=None: b'%PDF fake')

    def test_reissue_prints_the_corrected_number(self, admin_client, instance,
                                                 no_pdf, no_email, no_render):
        inst, trainer = instance
        cert = certificate_service.issue_lecturer_certificate(inst, trainer)
        assert _event_segment(cert.number) == '1028974'
        inst.bpr_event_number = '1031500'
        db.session.commit()

        response = admin_client.post(
            f'/admin/instances/{inst.id}/lecturer-certificate/reissue',
            data={'cert_id': cert.id})

        assert response.status_code == 200
        db.session.refresh(cert)
        assert _event_segment(cert.number) == '1031500'

    def test_reissue_touches_only_the_addressed_trainer(self, admin_client,
                                                        instance, no_pdf,
                                                        no_email, no_render):
        """Межа мультитренерності: сусідній сертифікат лишається як був."""
        from app.services import trainer_links

        inst, first = instance
        second = Trainer(full_name='Другий Лектор',
                         full_name_dative='Другому Лектору',
                         slug=f'trainer-{_uid()}')
        db.session.add(second)
        db.session.flush()
        trainer_links.set_trainers(inst, [first.id, second.id])
        db.session.commit()
        first_cert = certificate_service.issue_lecturer_certificate(inst, first)
        second_cert = certificate_service.issue_lecturer_certificate(inst, second)
        untouched = second_cert.number
        inst.bpr_event_number = '1031500'
        db.session.commit()

        admin_client.post(
            f'/admin/instances/{inst.id}/lecturer-certificate/reissue',
            data={'cert_id': first_cert.id})

        db.session.refresh(first_cert)
        db.session.refresh(second_cert)
        assert _event_segment(first_cert.number) == '1031500'
        assert second_cert.number == untouched
        assert second_cert.recipient_name == 'Другому Лектору'

    def test_reissue_without_certificate_is_refused(self, admin_client, instance,
                                                    no_pdf, no_email):
        inst, _trainer = instance
        response = admin_client.post(
            f'/admin/instances/{inst.id}/lecturer-certificate/reissue',
            follow_redirects=True)

        assert 'Сертифікат не знайдено' in response.get_data(as_text=True)

    def test_reissue_refuses_a_certificate_of_another_event(self, admin_client,
                                                            instance, no_pdf,
                                                            no_email, no_render):
        """cert_id чужого заходу -- підміна у формі, а не робочий сценарій."""
        inst, trainer = instance
        cert = certificate_service.issue_lecturer_certificate(inst, trainer)
        other = CourseInstance(
            course_id=inst.course_id, status='completed', event_format='offline',
            start_date=datetime.now(timezone.utc) - timedelta(days=3))
        db.session.add(other)
        db.session.commit()

        response = admin_client.post(
            f'/admin/instances/{other.id}/lecturer-certificate/reissue',
            data={'cert_id': cert.id}, follow_redirects=True)

        assert 'Сертифікат не знайдено' in response.get_data(as_text=True)

    def test_card_hides_the_button_until_there_is_something_to_reissue(
            self, admin_client, instance, no_pdf, no_email):
        inst, trainer = instance
        before = admin_client.get(f'/admin/instances/{inst.id}/edit')
        assert 'lecturer-certificate/reissue' not in before.get_data(as_text=True)

        certificate_service.issue_lecturer_certificate(inst, trainer)
        after = admin_client.get(f'/admin/instances/{inst.id}/edit')

        assert 'lecturer-certificate/reissue' in after.get_data(as_text=True)
