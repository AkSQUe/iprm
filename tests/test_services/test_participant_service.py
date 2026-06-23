"""Tests for app.services.participant_service.upsert_participant."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.services import participant_service
from app.services.participant_service import ParticipantError


def _instance():
    course = Course(slug=f'evt-{uuid4().hex[:6]}', title='Event', base_price=0, is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published')
    db.session.add(inst)
    db.session.flush()
    return inst


def _data(instance_id, **over):
    data = {
        'instance_id': instance_id,
        'last_name': 'Петренко', 'first_name': 'Іван', 'middle_name': None,
        'email': None, 'phone': '+380501112233',
        'participant_type': None, 'birth_date': None, 'education': None,
        'workplace': None, 'position': None, 'specializations': [],
        'status': 'pending', 'payment_status': 'unpaid', 'payment_amount': None,
        'attended': False, 'cpd_points_awarded': None, 'experience_years': None,
        'license_number': None, 'admin_notes': None,
    }
    data.update(over)
    return data


def test_create_new_participant_sets_required_phone(app):
    """Регресія: створення нового учасника не падає на autoflush через
    user.medical_profile (phone NOT NULL мусить бути проставлений до flush)."""
    inst = _instance()
    reg, created = participant_service.upsert_participant(
        _data(inst.id), reg=None, on_duplicate='error',
    )
    db.session.flush()
    assert created is True
    assert reg.phone == '+380501112233'
    assert reg.id is not None


def test_create_duplicate_active_raises(app):
    inst = _instance()
    reg, _ = participant_service.upsert_participant(_data(inst.id), reg=None)
    db.session.flush()
    with pytest.raises(ParticipantError):
        participant_service.upsert_participant(
            _data(inst.id, email=reg.user.email), reg=None, on_duplicate='error',
        )


def test_create_reuses_user_by_email_on_other_event(app):
    inst1, inst2 = _instance(), _instance()
    reg1, _ = participant_service.upsert_participant(
        _data(inst1.id, email='same@test.com'), reg=None,
    )
    db.session.flush()
    reg2, _ = participant_service.upsert_participant(
        _data(inst2.id, email='same@test.com'), reg=None,
    )
    db.session.flush()
    assert reg2.user_id == reg1.user_id
    assert reg2.phone == '+380501112233'


def test_reactivate_cancelled_registration(app):
    inst = _instance()
    reg, _ = participant_service.upsert_participant(_data(inst.id, email='x@test.com'), reg=None)
    db.session.flush()
    reg.status = 'cancelled'
    db.session.flush()
    reg2, _ = participant_service.upsert_participant(
        _data(inst.id, email='x@test.com', status='confirmed'), reg=None,
    )
    db.session.flush()
    assert reg2.id == reg.id
    assert reg2.status == 'confirmed'
    assert reg2.phone == '+380501112233'
