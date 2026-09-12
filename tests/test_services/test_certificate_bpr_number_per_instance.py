"""Сегмент номера заходу в сертифікаті береться з ПРОВЕДЕННЯ, не з курсу.

Курс загальний, а в реєстрі БПР кожне подання має власний номер. Доки
сертифікат тягнув номер курсу, усі дати одного курсу виходили під одним
номером реєстру -- саме та підміна, яку ці тести й стережуть.
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


@pytest.fixture
def no_pdf(monkeypatch):
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')
    monkeypatch.setattr(certificate_service, '_write_lecturer_pdf',
                        lambda cert: '/dev/null', raising=False)


@pytest.fixture
def provider(app):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    db.session.commit()
    return settings


def _course(event_number='1028974'):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'inum-{uuid4().hex[:6]}',
        is_active=True, event_type='course',
        cpd_points_online=12, cpd_points_offline=12,
        bpr_event_number=event_number,
        bpr_lecturer_points=5,
    )
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, event_number=None):
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ', bpr_event_number=event_number,
        start_date=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _registration(instance):
    user = User.create_with_password(
        f'inum-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True,
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='completed',
        payment_status='paid', attended=True,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


def _event_segment(number):
    """РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ -> ЗЗЗЗЗЗЗ."""
    return number.split('-')[2]


def test_participant_number_uses_instance_override(app, provider, no_pdf):
    course = _course('1028974')
    instance = _instance(course, event_number='1031500')
    reg = _registration(instance)
    db.session.commit()

    cert = certificate_service.issue_certificate(reg)

    assert _event_segment(cert.number) == '1031500'


def test_participant_number_falls_back_to_course(app, provider, no_pdf):
    course = _course('1028974')
    instance = _instance(course, event_number=None)
    reg = _registration(instance)
    db.session.commit()

    cert = certificate_service.issue_certificate(reg)

    assert _event_segment(cert.number) == '1028974'


def test_two_dates_of_one_course_get_different_event_segments(app, provider, no_pdf):
    course = _course('1028974')
    first = _registration(_instance(course, event_number='1031500'))
    second = _registration(_instance(course, event_number='1031501'))
    db.session.commit()

    first_cert = certificate_service.issue_certificate(first)
    second_cert = certificate_service.issue_certificate(second)

    assert _event_segment(first_cert.number) == '1031500'
    assert _event_segment(second_cert.number) == '1031501'


def test_course_without_number_still_issues_when_instance_has_one(app, provider, no_pdf):
    """Номер, що живе лише на даті, -- штатний випадок, а не помилка."""
    course = _course(event_number=None)
    reg = _registration(_instance(course, event_number='1031500'))
    db.session.commit()

    cert = certificate_service.issue_certificate(reg)

    assert _event_segment(cert.number) == '1031500'


def test_no_number_anywhere_refuses_to_issue(app, provider, no_pdf):
    course = _course(event_number=None)
    reg = _registration(_instance(course, event_number=None))
    db.session.commit()

    with pytest.raises(ValueError, match='номер заходу БПР'):
        certificate_service.issue_certificate(reg)


def test_lecturer_number_uses_instance_override(app, provider, no_pdf):
    course = _course('1028974')
    trainer = Trainer(full_name='Тренер Тренерович',
                      full_name_dative='Тренеру Тренеровичу',
                      slug=f'trainer-{uuid4().hex[:6]}')
    db.session.add(trainer)
    db.session.flush()
    instance = _instance(course, event_number='1031500')
    instance.trainer_id = trainer.id
    db.session.commit()

    cert = certificate_service.issue_lecturer_certificate(instance)

    assert _event_segment(cert.number) == '1031500'
