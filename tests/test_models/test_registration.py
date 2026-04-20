import pytest

from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User


def _make_course_with_instance(db_session, slug):
    course = Course(title='C', slug=slug)
    db_session.add(course)
    db_session.flush()
    inst = CourseInstance(course_id=course.id, status='published')
    db_session.add(inst)
    db_session.flush()
    return inst


def test_registration_creation(db_session):
    """Створення реєстрації (прив'язана до CourseInstance)."""
    user = User(email='reg@test.com', password='pass1234')
    inst = _make_course_with_instance(db_session, 'e-reg')
    db_session.add(user)
    db_session.flush()

    reg = EventRegistration(
        user_id=user.id,
        instance_id=inst.id,
        phone='+380501234567',
        specialty='Dentist',
        workplace='Clinic X',
    )
    db_session.add(reg)
    db_session.flush()

    assert reg.id is not None
    assert reg.status == 'pending'
    assert reg.payment_status == 'unpaid'
    assert reg.status_label == 'Очікує'
    assert reg.payment_status_label == 'Не оплачено'


def test_registration_unique_constraint(db_session):
    """Один користувач -- одна реєстрація на конкретне проведення."""
    user = User(email='dup@test.com', password='pass1234')
    inst = _make_course_with_instance(db_session, 'e-dup')
    db_session.add(user)
    db_session.flush()

    reg1 = EventRegistration(
        user_id=user.id, instance_id=inst.id,
        phone='+380', specialty='S', workplace='W',
    )
    db_session.add(reg1)
    db_session.flush()

    reg2 = EventRegistration(
        user_id=user.id, instance_id=inst.id,
        phone='+380', specialty='S', workplace='W',
    )
    db_session.add(reg2)
    with pytest.raises(Exception):
        db_session.flush()


def test_registration_relationships(db_session):
    """Зв'язки user та instance.course."""
    user = User(email='rel@test.com', password='pass1234')
    inst = _make_course_with_instance(db_session, 'e-rel')
    db_session.add(user)
    db_session.flush()

    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id,
        phone='+380', specialty='S', workplace='W',
    )
    db_session.add(reg)
    db_session.flush()

    assert reg.user.email == 'rel@test.com'
    assert reg.instance.course.slug == 'e-rel'
