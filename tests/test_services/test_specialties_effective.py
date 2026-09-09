"""Ефективний список спеціальностей проведення і звірка старого тексту."""
import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.specialty import Specialty
from app.services import specialties


@pytest.fixture
def course(app):
    row = Course(title='Курс плазмотерапії', slug='kurs-plazmoterapii',
                 bpr_specialty_codes=['alerholohiia'])
    db.session.add(row)
    db.session.commit()
    return row


def test_instance_inherits_course_codes(course):
    instance = CourseInstance(course_id=course.id)
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_specialty_codes == ['alerholohiia']


def test_instance_override_wins(course):
    instance = CourseInstance(course_id=course.id,
                              bpr_specialty_codes=['dermatovenerolohiia'])
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_specialty_codes == ['dermatovenerolohiia']


def test_empty_override_falls_back_to_course(course):
    instance = CourseInstance(course_id=course.id, bpr_specialty_codes=[])
    db.session.add(instance)
    db.session.commit()
    assert instance.effective_specialty_codes == ['alerholohiia']


def test_legacy_text_matches_known_name():
    name_to_code = {'усі лікарські спеціальності': 'all-medical'}
    assert specialties.legacy_code_for('  Усі лікарські  спеціальності ',
                                       name_to_code) == ('all-medical', None)


def test_legacy_text_without_match_becomes_new_row():
    name_to_code = {'усі лікарські спеціальності': 'all-medical'}
    code, missing = specialties.legacy_code_for('Косметологія та дерматологія',
                                                name_to_code)
    assert missing == 'Косметологія та дерматологія'
    assert code and code not in name_to_code.values()


def test_usage_counts_courses_and_instances(app, course):
    db.session.add(CourseInstance(course_id=course.id,
                                  bpr_specialty_codes=['dermatovenerolohiia']))
    db.session.add(Specialty(code='alerholohiia', name='Алергологія', section='medical',
                             sort_order=2))
    db.session.commit()
    counts = specialties.usage()
    assert counts.get('alerholohiia') == 1
    assert counts.get('dermatovenerolohiia') == 1
