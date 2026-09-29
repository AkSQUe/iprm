"""Нумерація сертифікатів: порядковий номер у межах заходу.

Сегмент «номер учасника» спершу брався як COUNT(*) + 1 (однакові номери
одночасним видачам, відкат назад після видалення), потім -- одним лічильником
на весь сайт (номери заходу йшли не з одиниці й перемішувались із сусідніми).
Тепер лічильник свій у кожного префікса РРРР-ПППП-ЗЗЗЗЗЗЗ.

Тут перевіряємо, що нумерація в кожного заходу своя й починається з одиниці,
що вона монотонна й не залежить від видалень, і що повторна видача
відкликаного сертифіката не перенумеровує його.
"""
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.certificate_number_counter import CertificateNumberCounter
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import certificate_service


PROVIDER = '2738'

# `issue_certificate` комітить сам (PDF пишеться до коміту), тож створені ним
# рядки переживають відкат фікстури db_session і видні наступним тестам. Щоб
# тести не залежали від порядку, кожна реєстрація отримує ВЛАСНИЙ номер заходу
# БПР -- а з ним і власний лічильник, що починається з нуля.
_event_numbers = count(1000000)

# Відрізнити "номер не передали" від явного None (кейс "номер заходу не задано").
_AUTO = object()


@pytest.fixture(autouse=True)
def bpr_settings(app):
    """Провайдер БПР заданий."""
    settings = SiteSettings.get()
    settings.bpr_provider_number = PROVIDER
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
        is_active=True, event_type='course',
        # _event_snapshot бере відкат балів через due_cpd_points, який
        # читає лише розщеплені колонки.
        cpd_points_online=cpd_points, cpd_points_offline=cpd_points,
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


def _counter(reg, kind='participant'):
    """Значення лічильника заходу цієї реєстрації (0 -- рядка ще немає)."""
    prefix = Certificate.format_prefix(
        reg.instance.start_date.year, PROVIDER, reg.instance.course.bpr_event_number)
    row = db.session.get(CertificateNumberCounter, (prefix, kind))
    return row.last_value if row else 0


# --- формат ------------------------------------------------------------------

def test_format_pads_segments():
    assert Certificate.format_number(2026, '2738', '1028974', 4) == \
        '2026-2738-1028974-000004'


def test_format_pads_short_provider_and_event():
    assert Certificate.format_number(2026, '27', '974', 1) == \
        '2026-0027-0000974-000001'


@pytest.mark.parametrize('number, expected', [
    ('2026-2738-1028974-000004', ('2026-2738-1028974', 4)),
    ('2026-2738-1028974-100001', ('2026-2738-1028974', 100001)),
    (' 2026-2738-1028974-000005 ', ('2026-2738-1028974', 5)),
    ('IPRM-2026-000001', None),
    ('2026-2738-1028974', None),
    ('', None),
    (None, None),
])
def test_split_number(number, expected):
    assert Certificate.split_number(number) == expected


# --- лічильник заходу --------------------------------------------------------

def test_each_event_starts_from_one(app, no_pdf):
    """Головна вимога: номер учасника рахується в межах заходу, а не сайту."""
    first_event = [
        certificate_service.issue_certificate(_registration(event_num='1400001'))
        for _ in range(3)
    ]
    second_event = certificate_service.issue_certificate(
        _registration(event_num='1400002'))

    assert [c.number[-6:] for c in first_event] == ['000001', '000002', '000003']
    assert second_event.number.endswith('-1400002-000001')


def test_late_certificate_continues_its_own_event(app, no_pdf):
    """Сценарій зі звіту: дописаний до минулого заходу сертифікат бере
    наступний номер СВОГО заходу, а не номер з-за хвоста наступного."""
    past = [_registration(event_num='1400011') for _ in range(3)]
    for reg in past[:2]:
        certificate_service.issue_certificate(reg)
    for _ in range(4):
        certificate_service.issue_certificate(_registration(event_num='1400012'))

    late = certificate_service.issue_certificate(past[2])

    assert late.number.endswith('-1400011-000003')


def test_year_is_part_of_the_event(app, no_pdf):
    """Той самий номер заходу в інший рік -- інший префікс, нумерація з одиниці."""
    certificate_service.issue_certificate(_registration(event_num='1400021'))
    other_year = _registration(event_num='1400021')
    other_year.instance.start_date = datetime(2025, 3, 1, tzinfo=timezone.utc)
    db.session.flush()

    cert = certificate_service.issue_certificate(other_year)

    assert cert.number == '2025-2738-1400021-000001'


def test_participant_and_lecturer_counters_are_independent(app):
    year = datetime.now(timezone.utc).year
    event_num = str(next(_event_numbers))
    participant = certificate_service._next_free_number(year, PROVIDER, event_num)
    lecturer = certificate_service._next_free_number(
        year, PROVIDER, event_num, kind='lecturer')
    assert participant.endswith('-000001')
    assert lecturer.endswith('-100001')


def test_counter_survives_deletion(app, no_pdf):
    """Видалений сертифікат не віддає свій номер наступній людині:
    перший уже міг піти в реєстр."""
    event_num = str(next(_event_numbers))
    first = certificate_service.issue_certificate(_registration(event_num=event_num))
    number = first.number
    db.session.delete(first)
    db.session.flush()

    second_reg = _registration(event_num=event_num)
    second = certificate_service.issue_certificate(second_reg)
    assert second.number != number, 'номер повторився після видалення'
    assert _counter(second_reg) == 2


def test_backfilled_counter_continues_numbering(app, no_pdf):
    """Бекфіл міграції = максимальний наявний сегмент заходу; далі 000004."""
    reg = _registration()
    prefix = Certificate.format_prefix(
        reg.instance.start_date.year, PROVIDER, reg.instance.course.bpr_event_number)
    db.session.add(CertificateNumberCounter(prefix=prefix, kind='participant',
                                            last_value=3))
    db.session.flush()

    cert = certificate_service.issue_certificate(reg)
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
    assert _counter(reg) == 1


def test_issue_is_idempotent_for_valid_certificate(app, no_pdf):
    reg = _registration()
    first = certificate_service.issue_certificate(reg)
    second = certificate_service.issue_certificate(reg)
    assert first.id == second.id
    assert _counter(reg) == 1


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
    """Перевірка БПР-полів стоїть ДО виділення номера: рядок лічильника
    навіть не з'являється."""
    before = CertificateNumberCounter.query.count()
    with pytest.raises(ValueError):
        certificate_service.issue_certificate(_registration(event_num=None))
    assert CertificateNumberCounter.query.count() == before


# --- свіже значення з-під блокування ----------------------------------------
#
# Рядок лічильника може вже лежати в identity map, а для завантаженої сутності
# SQLAlchemy без `populate_existing()` не перезаписує атрибути. Лічильник тоді
# рахувався б від значення, прочитаного ДО блокування, і дві одночасні видачі
# отримали б один номер -- так уже ламався попередній, загальний лічильник.
#
# Конкурентність тут не імітуємо -- достатньо зафіксувати механіку: якщо рядок
# у БД змінився в обхід ORM, читання під блокуванням мусить це побачити.

def test_locked_read_sees_value_from_db_not_from_session(app):
    from sqlalchemy import text

    prefix = f'2026-{PROVIDER}-{next(_event_numbers)}'
    row = CertificateNumberCounter(prefix=prefix, kind='participant', last_value=100)
    db.session.add(row)
    db.session.commit()
    assert row.last_value == 100  # рядок лежить у сесії

    db.session.execute(
        text('UPDATE certificate_number_counters SET last_value = 500 '
             'WHERE prefix = :p AND kind = :k'),
        {'p': prefix, 'k': 'participant'},
    )

    assert certificate_service._allocate_number_segment(prefix, 'participant') == 501, (
        'лічильник порахований від значення в сесії, а не з-під блокування'
    )


def test_allocation_persists_incremented_value(app):
    """Значення мусить лягти в рядок, інакше наступна видача візьме те саме."""
    prefix = f'2026-{PROVIDER}-{next(_event_numbers)}'

    first = certificate_service._allocate_number_segment(prefix, 'lecturer')
    second = certificate_service._allocate_number_segment(prefix, 'lecturer')

    assert (first, second) == (1, 2)
    db.session.expire_all()
    row = db.session.get(CertificateNumberCounter, (prefix, 'lecturer'))
    assert row.last_value == 2
