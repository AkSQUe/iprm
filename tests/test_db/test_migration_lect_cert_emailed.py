"""Міграція lect_cert_emailed_20260922: колонка emailed_at.

Наявні сертифікати позначаються як уже опрацьовані (emailed_at = issued_at),
інакше перший же тік джоби розіслав би листи за минулі заходи.

Саму `upgrade()` тут не проганяємо: у тестовій схемі (create_all з моделей)
колонка вже є, тож add_column впав би на дублікаті. Натомість перевіряємо
SQL бекфілу й узгодженість ревізій.
"""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.lecturer_certificate import LecturerCertificate

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / 'migrations' / 'versions' / 'lect_cert_emailed_20260922.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_lect_cert_emailed', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_revision_chain(migration):
    """Ланцюжок ревізій мусить бути правильним."""
    assert migration.revision == 'lect_cert_emailed_20260922'
    assert migration.down_revision == 'email_trainer_reqs_20260919'


def test_backfill_sql_sets_emailed_at_from_issued_at(app, migration):
    """Бекфіл переносить issued_at у emailed_at для наявних сертифікатів.

    Це найважливіша вимога: без неї перша ж тарета джоби розіслала б листи
    за ВСІ минулі заходи, а не лише за нові.
    """
    # Створимо проведення й тренерський сертифікат без emailed_at.
    course = Course(
        title=f'К {uuid4().hex[:4]}', slug=f'bl-{uuid4().hex[:6]}',
        is_active=True, event_type='course'
    )
    db.session.add(course)
    db.session.flush()

    now = datetime.now(timezone.utc)
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        start_date=now
    )
    db.session.add(inst)
    db.session.flush()

    # Створимо сертифікат. issued_at заповниться за умовчанням,
    # emailed_at залишиться NULL.
    cert = LecturerCertificate(
        instance_id=inst.id, trainer_id=None, number='TEST-BACKFILL-001',
        recipient_name='Тестовому Лектору', event_title='Тестовий захід',
    )
    db.session.add(cert)
    db.session.flush()

    # Перевіримо що перед бекфілом emailed_at = NULL.
    assert cert.emailed_at is None
    issued_at_value = cert.issued_at

    # Виконаємо той самий бекфіл, що й у升級.
    db.session.execute(text(migration.BACKFILL_SQL))
    db.session.commit()

    # Перевіримо що після бекфілу emailed_at = issued_at.
    db.session.expire(cert)
    cert_refreshed = db.session.get(LecturerCertificate, cert.id)
    # Порівнюємо без часового поясу, бо БД може повернути без tzinfo.
    assert cert_refreshed.emailed_at is not None
    assert cert_refreshed.emailed_at.replace(tzinfo=None) == issued_at_value.replace(tzinfo=None)
