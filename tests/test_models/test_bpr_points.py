from decimal import Decimal
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.registration import EventRegistration
from app.models.user import User


def _course(**kw):
    # id(kw) -- зі спеки в брифі -- переприсвоюється після збирання сміття,
    # тож два тести можуть зіткнутись на UNIQUE(slug). uuid4 -- як у
    # tests/test_routes/test_api_v1.py.
    course = Course(title='Курс', slug=f'c-{uuid4().hex[:8]}', **kw)
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, **kw):
    inst = CourseInstance(course_id=course.id, **kw)
    db.session.add(inst)
    db.session.flush()
    return inst


def _registration(**kw):
    # user_id/phone/specialty/workplace -- NOT NULL у EventRegistration
    # незалежно від цієї задачі; бриф їх не наводить, тож добираємо самі.
    user = User(email=f'u-{uuid4().hex[:8]}@test.com')
    db.session.add(user)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, phone='+380501234567',
        specialty='Спеціальність', workplace='Місце роботи',
        **kw,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


def test_effective_cpd_for_takes_instance_value(app):
    course = _course(cpd_points_online=Decimal('5'), cpd_points_offline=Decimal('6'))
    inst = _instance(course, event_format='hybrid',
                     cpd_points_online=Decimal('7.5'),
                     cpd_points_offline=Decimal('9'))
    assert inst.effective_cpd_for('online') == Decimal('7.5')
    assert inst.effective_cpd_for('offline') == Decimal('9')


def test_effective_cpd_for_falls_back_to_course_per_format(app):
    course = _course(cpd_points_online=Decimal('5'), cpd_points_offline=Decimal('6'))
    inst = _instance(course, event_format='hybrid', cpd_points_online=Decimal('7.5'))
    assert inst.effective_cpd_for('online') == Decimal('7.5')
    # Порожнє офлайнове НЕ підміняється онлайновим -- відкат тільки на курс.
    assert inst.effective_cpd_for('offline') == Decimal('6')


def test_effective_cpd_for_empty_everywhere_is_none(app):
    course = _course()
    inst = _instance(course, event_format='online')
    assert inst.effective_cpd_for('online') is None


def test_cpd_pairs_only_formats_the_event_has(app):
    course = _course()
    inst = _instance(course, event_format='online',
                     cpd_points_online=Decimal('7.5'),
                     cpd_points_offline=Decimal('9'))
    assert inst.cpd_pairs == [('online', Decimal('7.5'))]


def test_cpd_pairs_hybrid_gives_both(app):
    course = _course()
    inst = _instance(course, event_format='hybrid',
                     cpd_points_online=Decimal('7.5'),
                     cpd_points_offline=Decimal('9'))
    assert inst.cpd_pairs == [('online', Decimal('7.5')), ('offline', Decimal('9'))]


def test_cpd_range(app):
    course = _course()
    inst = _instance(course, event_format='hybrid',
                     cpd_points_online=Decimal('7.5'),
                     cpd_points_offline=Decimal('9'))
    assert inst.cpd_range == (Decimal('7.5'), Decimal('9'))


def test_participation_format_prefers_own_column(app):
    course = _course()
    inst = _instance(course, event_format='hybrid')
    tariff = InstanceTariff(instance_id=inst.id, name='Онлайн',
                            price=Decimal('100'), event_format='online')
    db.session.add(tariff)
    db.session.flush()
    reg = _registration(instance_id=inst.id, tariff_id=tariff.id,
                        participation_format='offline')
    assert reg.effective_participation_format == 'offline'


def test_participation_format_falls_back_to_tariff(app):
    course = _course()
    inst = _instance(course, event_format='hybrid')
    tariff = InstanceTariff(instance_id=inst.id, name='Онлайн',
                            price=Decimal('100'), event_format='online')
    db.session.add(tariff)
    db.session.flush()
    reg = _registration(instance_id=inst.id, tariff_id=tariff.id)
    assert reg.effective_participation_format == 'online'


def test_participation_format_hybrid_without_tariff_is_offline(app):
    course = _course()
    inst = _instance(course, event_format='hybrid')
    reg = _registration(instance_id=inst.id)
    assert reg.effective_participation_format == 'offline'


def test_participation_format_online_event_without_tariff(app):
    course = _course()
    inst = _instance(course, event_format='online')
    reg = _registration(instance_id=inst.id)
    assert reg.effective_participation_format == 'online'


def test_due_cpd_points_uses_participant_format(app):
    course = _course()
    inst = _instance(course, event_format='hybrid',
                     cpd_points_online=Decimal('7.5'),
                     cpd_points_offline=Decimal('9'))
    reg = _registration(instance_id=inst.id, participation_format='online')
    assert reg.due_cpd_points == Decimal('7.5')
