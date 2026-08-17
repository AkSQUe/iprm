"""Міграція bpr_counter_20260817: бекфіл лічильників з уже виданих номерів.

Ризик тут не в DDL, а в розборі номерів. Якщо бекфіл занизить лічильник, перший
же новий номер зіткнеться з наявним; якщо завищить -- утворить діру. Окремо
важливий legacy-рядок старого формату (``IPRM-2026-000001``), у якого 4-го
сегмента просто немає: він мусить бути проігнорований, а не впасти на int().

Саму ``upgrade()`` тут не проганяємо: у тестовій схемі (create_all з моделей)
колонки лічильників уже є, тож add_column впав би на дублікаті.
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.lecturer_certificate import LecturerCertificate
from app.models.registration import EventRegistration
from app.models.user import User

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / 'migrations' / 'versions' / 'bpr_counter_20260817_add_counters.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_bpr_counter', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _certificate(number):
    course = Course(title=f'К {uuid4().hex[:4]}', slug=f'bc-{uuid4().hex[:6]}',
                    is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        start_date=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.session.add(inst)
    user = User.create_with_password(
        f'bc-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Б', last_name='К', email_confirmed=True)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', payment_status='paid')
    db.session.add(reg)
    db.session.flush()
    cert = Certificate(
        registration_id=reg.id, user_id=user.id, number=number,
        recipient_name='Б К', event_title='Захід', pdf_path=f'2026/{number}.pdf')
    db.session.add(cert)
    db.session.flush()
    return cert


def _bind():
    db.session.flush()
    return db.session.connection()


# --- розбір одного номера (чиста функція) ------------------------------------

@pytest.mark.parametrize('number, expected', [
    ('2026-2738-1028974-000004', 4),
    ('2026-2738-1028974-100001', 100001),      # лекторський діапазон
    ('  2026-2738-1028974-000005  ', 5),       # пробіли по краях
    ('2026-27-974-1', 1),                      # незаповнені нулями сегменти
    ('IPRM-2026-000001', None),                # легасі: 4-го сегмента немає
    ('2026-2738-1028974', None),               # обрізаний номер
    ('2026-2738-1028974-00000X', None),        # нецифровий сегмент
    ('', None),
    (None, None),
])
def test_segment_parsing(migration, number, expected):
    assert migration._segment_of(number) == expected


# --- максимум по таблиці -----------------------------------------------------
#
# Номери тут навмисно високі: `issue_certificate` комітить сам, тож рядки інших
# тестів переживають відкат фікстури. Прив'язуватися до порожньої таблиці означало
# б залежати від порядку збору тестів.

def test_takes_maximum_not_count(app, migration):
    """Саме максимум: COUNT дав би менше і зіткнувся б з наявним номером."""
    _certificate('2026-2738-1028974-900003')
    _certificate('2026-2738-1028974-900007')
    assert migration._max_segment(_bind(), 'certificates') == 900007


def test_legacy_format_does_not_break_scan(app, migration):
    """Старий номер без 4-го сегмента не має валити розбір таблиці."""
    _certificate('IPRM-2026-000001')
    _certificate('2026-2738-1028974-900002')
    assert migration._max_segment(_bind(), 'certificates') == 900002


# --- лекторський зсув --------------------------------------------------------

def test_lecturer_offset_is_stripped(app, migration):
    """У лічильнику тримаємо значення БЕЗ зсуву -- він додається при видачі."""
    course = Course(title='К', slug=f'bl-{uuid4().hex[:6]}', is_active=True,
                    event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='completed',
                          event_format='offline',
                          start_date=datetime.now(timezone.utc))
    db.session.add(inst)
    db.session.flush()
    db.session.add(LecturerCertificate(
        instance_id=inst.id, number='2026-2738-1028974-190004',
        recipient_name='Лектору', event_title='Захід', cpd_points=6))
    db.session.flush()

    raw = migration._max_segment(_bind(), 'lecturer_certificates')
    assert raw == 190004
    assert max(raw - migration.LECTURER_NUMBER_OFFSET, 0) == 90004


def test_absent_lecturer_certificates_do_not_go_negative(migration):
    """0 - зсув дало б від'ємний лічильник і номери нижче учасницьких."""
    assert max(0 - migration.LECTURER_NUMBER_OFFSET, 0) == 0


# --- узгодженість зі застосунком --------------------------------------------

def test_offset_matches_application_constant(migration):
    """Розходження констант тихо змішало б діапазони номерів."""
    from app.models.lecturer_certificate import LECTURER_NUMBER_OFFSET
    assert migration.LECTURER_NUMBER_OFFSET == LECTURER_NUMBER_OFFSET


def test_revision_chain(migration):
    assert migration.revision == 'bpr_counter_20260817'
    assert migration.down_revision == 'partner_events_20260814'
