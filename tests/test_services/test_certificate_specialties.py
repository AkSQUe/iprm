"""Рядок «Спеціальності:» у сертифікаті: джерело, порядок, розмір шрифту."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.specialty import Specialty
from app.models.user import User
from app.services import certificate_service
from app.services.certificate_service import _specialties_size_class


def test_short_line_keeps_base_size():
    assert _specialties_size_class('Алергологія') == 'cert__meta-line--md'


def test_long_line_gets_smaller_class():
    line = ', '.join(['Дитяча кардіоревматологія'] * 6)
    assert _specialties_size_class(line) == 'cert__meta-line--xs'


def test_empty_line_is_md():
    assert _specialties_size_class('') == 'cert__meta-line--md'


def test_mid_length_line_gets_sm_class():
    # ~110 символів -- типовий реальний перелік із 5-6 назв довідника.
    line = ', '.join(['Дерматовенерологія', 'Ендокринологія', 'Кардіологія',
                      'Неврологія', 'Педіатрія'])
    assert _specialties_size_class(line) == 'cert__meta-line--sm'


# --- знімок сертифіката: джерело й незалежність від подальших правок довідника ---

@pytest.fixture
def _no_pdf(monkeypatch):
    """Не малювати PDF при видачі сертифіката -- WeasyPrint тут не тестуємо."""
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')


def _registration_with_codes(codes):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'cert-spec-line-{uuid4().hex[:6]}',
        is_active=True, event_type='course', bpr_event_number=str(uuid4().int)[:7],
        bpr_specialty_codes=codes,
    )
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ', start_date=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.session.add(instance)
    user = User.create_with_password(
        f'cert-spec-line-{uuid4().hex[:6]}@test.com', 'password123',
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
    return reg


def test_snapshot_comes_from_effective_codes_in_directory_order(app, _no_pdf):
    """Знімок -- рядок довідника через кому, у порядку номенклатури, а не
    у порядку, в якому коди перелічені в bpr_specialty_codes."""
    db.session.add_all([
        Specialty(code='kardiolohiia', name='Кардіологія', section='medical',
                 sort_order=29),
        Specialty(code='alerholohiia', name='Алергологія', section='medical',
                 sort_order=2),
    ])
    db.session.commit()
    # Код "пізнішої" спеціальності навмисно першим у списку курсу.
    reg = _registration_with_codes(['kardiolohiia', 'alerholohiia'])

    cert = certificate_service.issue_certificate(reg)

    assert cert.specialties == 'Алергологія, Кардіологія'


def test_renaming_directory_row_after_issue_does_not_change_snapshot(app, _no_pdf):
    """Знімок -- це знімок: перейменування рядка довідника ПІСЛЯ видачі не
    повинно змінювати вже виданий сертифікат."""
    row = Specialty(code='alerholohiia', name='Алергологія', section='medical',
                    sort_order=2)
    db.session.add(row)
    db.session.commit()
    reg = _registration_with_codes(['alerholohiia'])

    cert = certificate_service.issue_certificate(reg)
    assert cert.specialties == 'Алергологія'

    row.name = 'Нова назва розділу'
    db.session.commit()

    db.session.refresh(cert)
    assert cert.specialties == 'Алергологія', (
        'знімок сертифіката не повинен стежити за подальшими правками довідника'
    )
