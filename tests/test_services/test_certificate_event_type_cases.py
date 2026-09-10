"""Відмінки виду заходу в сертифікатах.

Учасницький друкує "успішно завершив(-ла) <знахідний>", лекторський --
"лектору(-ці) <родовий>". До довідника знахідний брався як називний у
нижньому регістрі, через що жіночі назви давали "завершив(-ла)
конференція". Ці тести пінять правильні форми.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.services import certificate_service


def _instance(course_type='scientific_conference', instance_type=None):
    course = Course(title='К', slug=f'ce-{uuid4().hex[:6]}',
                    is_active=True, event_type=course_type)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, event_type=instance_type,
        start_date=datetime.now(timezone.utc) - timedelta(days=1),
        status='published',
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def test_participant_case_is_accusative_for_feminine_type(db_session):
    inst = _instance('scientific_conference')
    assert certificate_service.event_type_accusative_for(inst) == 'наукову конференцію'


def test_participant_case_for_masculine_type(db_session):
    inst = _instance('training')
    assert certificate_service.event_type_accusative_for(inst) == 'тренінг'


def test_lecturer_case_is_genitive(db_session):
    inst = _instance('professional_school')
    assert certificate_service.event_type_genitive_for(inst) == 'фахової (тематичної) школи'


def test_instance_override_wins_over_course_type(db_session):
    inst = _instance('seminar', instance_type='congress')
    assert certificate_service.event_type_accusative_for(inst) == 'конгрес'
    assert certificate_service.event_type_genitive_for(inst) == 'конгресу'


def test_no_type_yields_none_so_template_prints_default(db_session):
    inst = _instance(None)
    assert certificate_service.event_type_accusative_for(inst) is None
    assert certificate_service.event_type_genitive_for(inst) is None


def test_hardcoded_genitive_map_is_gone():
    assert not hasattr(certificate_service, '_EVENT_TYPE_GENITIVE'), (
        'відмінки живуть у довіднику, а не в мапі всередині служби'
    )
