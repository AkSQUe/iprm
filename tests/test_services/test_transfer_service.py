"""Запобіжники перенесення.

Кожен -- окремим тестом: список причин показується адміну як є, і "чому
кнопка неактивна" має бути видно з падіння одного тесту, а не з'ясовуватись
перебором.
"""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.registration_transfer import RegistrationTransfer
from app.models.user import User
from app.services import transfer_service
from tests.refund_fixtures import purge

PREFIX = 'rts-'


@pytest.fixture
def world(app):
    """Реєстрація на заході через 10 днів + вільний цільовий через 20."""
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    db.session.flush()
    user.set_password('x' * 12)
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=1500)
    db.session.add_all([src, dst])
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.commit()
    yield reg, src, dst, user, course
    purge(PREFIX, slug_prefix=PREFIX)


def test_clean_case_has_no_blockers(world):
    reg, src, dst, _, _ = world
    assert transfer_service.check(reg, dst) == []


def test_guard_1_source_event_too_close(world):
    reg, src, dst, _, _ = world
    src.start_date = utcnow() + timedelta(hours=47)
    db.session.commit()
    problems = transfer_service.check(reg, dst)
    assert any('поточного заходу' in p for p in problems)


def test_guard_2_target_event_too_close(world):
    reg, src, dst, _, _ = world
    dst.start_date = utcnow() + timedelta(hours=47)
    db.session.commit()
    problems = transfer_service.check(reg, dst)
    assert any('обраного заходу' in p for p in problems)


def test_guard_3_same_instance(world):
    reg, src, dst, _, _ = world
    problems = transfer_service.check(reg, src)
    assert any('той самий захід' in p for p in problems)


def test_guard_4_target_not_published(world):
    reg, src, dst, _, _ = world
    dst.status = 'draft'
    db.session.commit()
    problems = transfer_service.check(reg, dst)
    assert any('недоступний' in p for p in problems)


def test_guard_5_already_registered_on_target(world):
    """Без цього перенесення падає на uq_user_instance_registration --
    у момент коміту, вже після надсилання листа."""
    reg, src, dst, user, _ = world
    db.session.add(EventRegistration(
        user_id=user.id, instance_id=dst.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка',
    ))
    db.session.commit()
    problems = transfer_service.check(reg, dst)
    assert any('уже зареєстрований' in p for p in problems)


def test_guard_6_cancelled_registration(world):
    reg, src, dst, _, _ = world
    reg.status = 'cancelled'
    db.session.commit()
    assert any('скасовано' in p.lower() for p in transfer_service.check(reg, dst))


def test_guard_7_certificate_issued(world):
    """Certificate має чотири NOT NULL-поля понад FK -- number,
    recipient_name, event_title, pdf_path; без них падає сам INSERT."""
    reg, src, dst, user, _ = world
    db.session.add(Certificate(
        registration_id=reg.id, user_id=user.id, number=f'{PREFIX}0001',
        recipient_name='Тест Переносний', event_title='Курс переносу',
        pdf_path='certificates/rts-0001.pdf',
    ))
    db.session.commit()
    assert any('сертифікат' in p for p in transfer_service.check(reg, dst))


def test_guard_8_quiz_passed(world):
    reg, src, dst, _, _ = world
    reg.quiz_passed_at = utcnow()
    db.session.commit()
    assert any('тест' in p for p in transfer_service.check(reg, dst))


def test_guard_9_open_transfer_exists(world):
    reg, src, dst, _, _ = world
    db.session.add(RegistrationTransfer(
        registration_id=reg.id, from_instance_id=src.id, to_instance_id=dst.id,
        initiator='participant', tariff_decision='keep',
        state=RegistrationTransfer.STATE_AWAITING,
    ))
    db.session.commit()
    assert any('очікує відповіді' in p for p in transfer_service.check(reg, dst))


def test_check_without_target_runs_only_registration_guards(world):
    """Без цілі перевіряємо лише стан самої реєстрації -- саме так модалка
    вирішує, чи пропонувати заходи взагалі."""
    reg, src, dst, _, _ = world
    assert transfer_service.check(reg) == []
    reg.status = 'cancelled'
    db.session.commit()
    assert transfer_service.check(reg) != []


def test_eligible_instances_excludes_blocked(world):
    reg, src, dst, _, _ = world
    ids = [i.id for i in transfer_service.eligible_instances(reg)]
    assert dst.id in ids
    assert src.id not in ids


def test_eligible_instances_excludes_too_close(world):
    reg, src, dst, _, _ = world
    dst.start_date = utcnow() + timedelta(hours=12)
    db.session.commit()
    assert transfer_service.eligible_instances(reg) == []
