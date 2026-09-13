from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import quiz_service


@pytest.fixture(autouse=True)
def bpr_ready(app):
    # Гейт `bpr_is_configured` дивиться й на номер провайдера БПР -- без
    # нього він поверне False ще ДО перевірки балів, і тест перевірив би не
    # те, що заявлено.
    settings = SiteSettings.get()
    settings.bpr_provider_number = 'PRV-1'
    db.session.flush()
    return settings


def _hybrid_registration(participation_format):
    course = Course(
        title='Гібрид', slug=f'award-{participation_format}',
        bpr_event_number='EVT-1',
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, event_format='hybrid', status='active',
        cpd_points_online=Decimal('7.50'), cpd_points_offline=Decimal('9.00'),
    )
    db.session.add(inst)
    db.session.flush()
    # user_id/phone/specialty/workplace -- обов'язкові колонки реєстрації,
    # брифовий приклад цього не враховував.
    user = User.create_with_password(
        f'award-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка',
        participation_format=participation_format,
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def test_award_gives_online_points_to_online_participant(app):
    reg = _hybrid_registration('online')
    quiz_service.award_and_issue(reg)
    assert reg.cpd_points_awarded == Decimal('7.50')


def test_award_gives_offline_points_to_offline_participant(app):
    reg = _hybrid_registration('offline')
    quiz_service.award_and_issue(reg)
    assert reg.cpd_points_awarded == Decimal('9.00')


def test_gate_blocks_online_participant_when_only_offline_filled(app):
    reg = _hybrid_registration('online')
    reg.instance.cpd_points_online = None
    db.session.commit()
    assert quiz_service.bpr_is_configured(
        reg.instance, registration=reg,
    ) is False


def test_gate_allows_offline_participant_when_only_offline_filled(app):
    reg = _hybrid_registration('offline')
    reg.instance.cpd_points_online = None
    db.session.commit()
    assert quiz_service.bpr_is_configured(
        reg.instance, registration=reg,
    ) is True
