"""Ефективний список спеціальностей проведення і звірка старого тексту."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.admin.forms import CourseInstanceForm
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.specialty import Specialty
from app.models.user import User
from app.services import certificate_service, course_service, specialties


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


def test_populate_instance_from_form_empty_selection_becomes_none(app, course):
    """Порожній вибір у формі проведення -- це "як у курсу" (NULL), не []."""
    instance = CourseInstance(course_id=course.id,
                              bpr_specialty_codes=['dermatovenerolohiia'])
    db.session.add(instance)
    db.session.commit()

    with app.test_request_context():
        form = CourseInstanceForm(obj=instance)
        form.bpr_specialty_codes.data = []
        course_service.populate_instance_from_form(instance, form)

    assert instance.bpr_specialty_codes is None
    # І тоді ефективний список знову бере коди курсу.
    assert instance.effective_specialty_codes == ['alerholohiia']


@pytest.fixture
def _no_pdf(monkeypatch):
    """Не малювати PDF при видачі сертифіката -- WeasyPrint тут не тестуємо."""
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')


def test_certificate_snapshot_uses_instance_override_not_course_codes(app, _no_pdf):
    """Знімок сертифіката бере ЕФЕКТИВНИЙ список: перевизначення проведення
    має переважити спеціальності курсу, а не проігноруватись."""
    db.session.add_all([
        Specialty(code='alerholohiia', name='Алергологія', section='medical',
                 sort_order=2),
        Specialty(code='dermatovenerolohiia', name='Дерматовенерологія',
                 section='medical', sort_order=5),
    ])
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'cert-spec-{uuid4().hex[:6]}',
        is_active=True, event_type='course', bpr_event_number='1000555',
        bpr_specialty_codes=['alerholohiia'],
    )
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ', start_date=datetime.now(timezone.utc) - timedelta(days=5),
        bpr_specialty_codes=['dermatovenerolohiia'],
    )
    db.session.add(instance)
    user = User.create_with_password(
        f'cert-spec-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True,
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='completed',
        payment_status='paid', attended=True,
    )
    db.session.add(reg)
    db.session.commit()

    cert = certificate_service.issue_certificate(reg)

    assert cert.specialties == 'Дерматовенерологія'
