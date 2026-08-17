"""Нумерація сертифікатів: монотонний лічильник замість COUNT(*).

Сегмент «номер учасника» раніше брався як COUNT(*) + 1 по таблиці сертифікатів.
За ручної видачі (три сертифікати за весь час) це не проявлялось, але автовидача
після тестування робить обидва режими відмови досяжними:

1. дві одночасні видачі брали ОДНЕ значення, а retry не сходився -- після
   rollback він перераховував ту саму кількість;
2. після видалення сертифіката лічильник ішов НАЗАД, і колізія з уже виданим
   номером ставала постійною.

Тут перевіряємо, що номер тепер монотонний, не залежить від видалень і що
повторна видача відкликаного сертифіката не перенумеровує його.
"""
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.lecturer_certificate import (
    LECTURER_NUMBER_OFFSET, LecturerCertificate,
)
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import certificate_service


PROVIDER = '2738'

# `issue_certificate` комітить сам (PDF пишеться до коміту), тож створені ним
# рядки переживають відкат фікстури db_session і видні наступним тестам. Щоб
# тести не залежали від порядку, кожна реєстрація отримує ВЛАСНИЙ номер заходу
# БПР -- тоді номери сертифікатів різних тестів не можуть зіткнутися, бо
# відрізняються третім сегментом.
_event_numbers = count(1000000)

# Відрізнити "номер не передали" від явного None (кейс "номер заходу не задано").
_AUTO = object()


@pytest.fixture(autouse=True)
def bpr_settings(app):
    """Провайдер БПР заданий, лічильники з нуля."""
    settings = SiteSettings.get()
    settings.bpr_provider_number = PROVIDER
    settings.bpr_participant_counter = 0
    settings.bpr_lecturer_counter = 0
    db.session.flush()
    return settings


@pytest.fixture
def no_pdf(monkeypatch):
    """Не малювати PDF: WeasyPrint тут не тестуємо, і він повільний."""
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')


def _registration(cpd_points=12, event_num=_AUTO):
    if event_num is _AUTO:
        event_num = str(next(_event_numbers))
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'cn-{uuid4().hex[:6]}',
        is_active=True, event_type='course', cpd_points=cpd_points,
        bpr_event_number=event_num,
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ',
        start_date=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db.session.add(inst)
    user = User.create_with_password(
        f'c-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True,
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='completed',
        payment_status='paid', attended=True,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


# --- формат ------------------------------------------------------------------

def test_format_pads_segments():
    assert Certificate.format_number(2026, '2738', '1028974', 4) == \
        '2026-2738-1028974-000004'


def test_format_pads_short_provider_and_event():
    assert Certificate.format_number(2026, '27', '974', 1) == \
        '2026-0027-0000974-000001'


# --- лічильник ---------------------------------------------------------------

def test_counter_is_monotonic(app):
    got = [certificate_service._allocate_number_segment('participant')
           for _ in range(3)]
    assert got == [1, 2, 3]


def test_counters_are_independent(app):
    certificate_service._allocate_number_segment('participant')
    certificate_service._allocate_number_segment('participant')
    assert certificate_service._allocate_number_segment('lecturer') == 1


def test_counter_survives_deletion(app, no_pdf):
    """Головний регрес: COUNT(*) після видалення йшов назад назовсім."""
    first = certificate_service.issue_certificate(_registration())
    number = first.number
    db.session.delete(first)
    db.session.flush()

    second = certificate_service.issue_certificate(_registration())
    assert second.number != number, 'номер повторився після видалення'
    assert SiteSettings.get().bpr_participant_counter == 2


def test_backfilled_counter_continues_numbering(app, no_pdf, bpr_settings):
    """Бекфіл міграції = максимальний наявний сегмент; далі 000004."""
    bpr_settings.bpr_participant_counter = 3
    db.session.flush()

    cert = certificate_service.issue_certificate(_registration())
    assert cert.number.endswith('-000004')


# --- обхід зайнятих номерів --------------------------------------------------

def test_taken_number_is_skipped(app, no_pdf):
    """Номер, що потрапив у таблицю в обхід лічильника (ручна правка БД)."""
    reg = _registration()
    event_num = reg.instance.course.bpr_event_number
    # Займаємо саме той номер, який лічильник видасть першим.
    other = _registration(event_num=event_num)
    db.session.add(Certificate(
        registration_id=other.id, user_id=other.user_id,
        number=Certificate.format_number(
            reg.instance.start_date.year, PROVIDER, event_num, 1),
        recipient_name='Чужий', event_title='Чужий захід',
        pdf_path='2026/squatter.pdf',
    ))
    db.session.flush()

    cert = certificate_service.issue_certificate(reg)
    assert cert.number.endswith('-000002')


def test_lecturer_number_does_not_collide_with_participant(app):
    year = datetime.now(timezone.utc).year
    event_num = str(next(_event_numbers))
    participant = certificate_service._next_free_number(year, PROVIDER, event_num)
    lecturer = certificate_service._next_free_number(
        year, PROVIDER, event_num,
        kind='lecturer', offset=LECTURER_NUMBER_OFFSET,
    )
    assert participant.endswith('-000001')
    assert lecturer.endswith('-100001')


# --- повторна видача ---------------------------------------------------------

def test_reissue_of_revoked_keeps_number_and_path(app, no_pdf):
    """Номер уже пішов у реєстр БПР і на руки -- мовчки змінювати його не можна.

    Заодно перевіряємо pdf_path: він збирався з issued_at.year, тож сертифікат,
    відкликаний у грудні й виданий знову у січні, отримував новий шлях при тому
    самому номері, а старий файл ставав сиротою.
    """
    reg = _registration()
    cert = certificate_service.issue_certificate(reg)
    number, pdf_path = cert.number, cert.pdf_path

    cert.revoked = True
    cert.revoked_at = datetime.now(timezone.utc)
    db.session.flush()

    again = certificate_service.issue_certificate(reg)
    assert again.id == cert.id
    assert again.number == number
    assert again.pdf_path == pdf_path
    assert again.revoked is False
    # Лічильник не витрачено: нового номера не виділяли.
    assert SiteSettings.get().bpr_participant_counter == 1


def test_issue_is_idempotent_for_valid_certificate(app, no_pdf):
    reg = _registration()
    first = certificate_service.issue_certificate(reg)
    second = certificate_service.issue_certificate(reg)
    assert first.id == second.id
    assert SiteSettings.get().bpr_participant_counter == 1


def test_pdf_path_year_follows_event_not_issue_date(app, no_pdf):
    """Тека мусить відповідати року в самому номері."""
    reg = _registration()
    reg.instance.start_date = datetime(2025, 12, 20, tzinfo=timezone.utc)
    db.session.flush()

    cert = certificate_service.issue_certificate(reg)
    assert cert.number.startswith('2025-')
    assert cert.pdf_path.startswith('2025/')


# --- незаповнена БПР-конфігурація -------------------------------------------

def test_missing_provider_number_raises(app, no_pdf, bpr_settings):
    bpr_settings.bpr_provider_number = ''
    db.session.flush()
    with pytest.raises(ValueError, match='провайдера'):
        certificate_service.issue_certificate(_registration())


def test_missing_event_number_raises(app, no_pdf):
    with pytest.raises(ValueError, match='заходу'):
        certificate_service.issue_certificate(_registration(event_num=None))


def test_failed_issue_does_not_burn_counter(app, no_pdf):
    """Перевірка БПР-полів стоїть ДО виділення номера."""
    with pytest.raises(ValueError):
        certificate_service.issue_certificate(_registration(event_num=None))
    assert SiteSettings.get().bpr_participant_counter == 0
