"""Присутність у три стани, прапорець закриття звітом, дата подачі звіту."""
from datetime import date

import pytest

from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import ATTENDANCE_LABELS, EventRegistration
from app.models.user import User


@pytest.fixture
def instance(db_session):
    course = Course(title='C', slug='att-course')
    db_session.add(course)
    db_session.flush()
    inst = CourseInstance(course_id=course.id, status='published')
    db_session.add(inst)
    db_session.flush()
    return inst


@pytest.fixture
def user(db_session):
    usr = User(email='att@test.com', password='pass1234')
    db_session.add(usr)
    db_session.flush()
    return usr


@pytest.fixture
def reg(db_session, instance, user):
    row = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380',
        specialty='S', workplace='W', status='confirmed',
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_attendance_three_states(reg):
    reg.attended = None
    assert reg.attendance is None
    assert reg.attendance_label == 'Не відмічено'
    reg.attended = False
    assert reg.attendance == 'absent'
    assert reg.attendance_label == "Не з'явився"
    reg.attended = True
    assert reg.attendance == 'present'
    assert reg.attendance_label == 'Був'


def test_labels_constant_matches_states():
    assert ATTENDANCE_LABELS == {
        'present': 'Був', 'absent': "Не з'явився", None: 'Не відмічено',
    }


def test_new_registration_is_unmarked(reg):
    assert reg.attended is None
    assert reg.completed_by_report is False


def test_instance_report_flag(instance):
    assert instance.bpr_report_submitted is False
    instance.bpr_report_submitted_on = date(2026, 11, 20)
    assert instance.bpr_report_submitted is True
