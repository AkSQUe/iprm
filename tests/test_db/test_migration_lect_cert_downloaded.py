"""Міграція lect_cert_downloaded_20260923: колонка downloaded_at.

Наявним сертифікатам ставиться downloaded_at = issued_at: без цього в кожного
тренера одразу засвітилися б «нові» документи за всі минулі заходи.

`upgrade()` тут не проганяємо -- тестова схема з create_all уже має колонку
(та сама причина, що й у test_migration_lect_cert_emailed.py); перевіряємо
SQL бекфілу на реальному рядку й ланцюжок ревізій.
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
    / 'migrations' / 'versions' / 'lect_cert_downloaded_20260923.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_lect_cert_downloaded', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_revision_chain(migration):
    assert migration.revision == 'lect_cert_downloaded_20260923'
    assert migration.down_revision == 'email_attachments_20260923'


def test_backfill_marks_existing_certificates_as_seen(app, migration):
    course = Course(title='Курс', slug=f'dl-{uuid4().hex[:8]}', is_active=True,
                    event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='completed', event_format='offline',
                          start_date=datetime.now(timezone.utc))
    db.session.add(inst)
    db.session.flush()
    issued_at = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    cert = LecturerCertificate(
        instance_id=inst.id, number=f'2026-2738-{uuid4().hex[:6]}-100001',
        recipient_name='Лектору', event_title='Захід', issued_at=issued_at,
    )
    db.session.add(cert)
    db.session.commit()
    assert cert.downloaded_at is None

    db.session.execute(text(migration.BACKFILL_SQL))
    db.session.commit()
    db.session.refresh(cert)
    assert cert.downloaded_at is not None
    assert cert.downloaded_at.replace(tzinfo=None) == issued_at.replace(tzinfo=None)
