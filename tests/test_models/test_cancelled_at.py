"""Дата скасування (CancellableMixin): ставиться на будь-якому шляху.

Фінзвіт відносить утримане до виручки на дату скасування, тож дата мусить
з'являтися саме в момент переходу в «скасовано», не зсуватися з
наступними правками і зникати, коли замовлення відновили.
"""
from datetime import datetime, timezone

from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.registration import EventRegistration
from app.models.user import User


def _reg(db_session, slug, status='confirmed'):
    course = Course(title='C', slug=slug)
    db_session.add(course)
    db_session.flush()
    inst = CourseInstance(course_id=course.id, status='published')
    user = User(email=f'{slug}@test.com', password='pass1234')
    db_session.add_all([inst, user])
    db_session.flush()
    reg = EventRegistration(user_id=user.id, instance_id=inst.id, phone='+380',
                            specialty='S', workplace='W', status=status)
    db_session.add(reg)
    db_session.flush()
    return reg


def test_cancelling_stamps_the_moment(db_session):
    reg = _reg(db_session, 'cx-stamp')
    assert reg.cancelled_at is None

    reg.status = 'cancelled'
    db_session.flush()

    assert reg.cancelled_at is not None


def test_later_edits_do_not_move_it(db_session):
    reg = _reg(db_session, 'cx-keep')
    reg.status = 'cancelled'
    db_session.flush()
    stamped = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
    reg.cancelled_at = stamped
    db_session.flush()

    reg.notes = 'дзвонили'
    reg.status = 'cancelled'
    db_session.flush()

    assert reg.cancelled_at.replace(tzinfo=timezone.utc) == stamped


def test_restoring_clears_it(db_session):
    reg = _reg(db_session, 'cx-restore')
    reg.status = 'cancelled'
    db_session.flush()

    reg.status = 'confirmed'
    db_session.flush()

    assert reg.cancelled_at is None


def test_created_cancelled_is_stamped(db_session):
    reg = _reg(db_session, 'cx-new', status='cancelled')

    assert reg.cancelled_at is not None


def test_full_refund_path_stamps_it(db_session):
    """Повне повернення саме переводить у «скасовано» (payment_ops)."""
    from app.services.payment_ops import PaymentOps

    reg = _reg(db_session, 'cx-refund')
    reg.payment_status = 'paid'
    reg.payment_amount = 1000
    db_session.flush()

    PaymentOps(None).update_payment_status(reg, 'refunded', source='refund')

    assert reg.status == 'cancelled'
    assert reg.cancelled_at is not None


def test_online_enrollment_too(db_session):
    course = OnlineCourse(sintegrum_id=90061010, remote_name='O', slug='cx-online')
    user = User(email='cx-online@test.com', password='pass1234')
    db_session.add_all([course, user])
    db_session.flush()
    item = OnlineEnrollment(user_id=user.id, online_course_id=course.id,
                            payment_amount=100)
    db_session.add(item)
    db_session.flush()

    item.status = 'cancelled'
    db_session.flush()

    assert item.cancelled_at is not None
