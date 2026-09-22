"""Міграція lect_cert_emailed_20260922: колонка emailed_at.

Наявні сертифікати позначаються як уже опрацьовані (emailed_at = issued_at),
інакше перший же тік джоби розіслав би листи за минулі заходи.
"""
from app.extensions import db
from app.models.lecturer_certificate import LecturerCertificate


def test_emailed_at_defaults_to_null_for_new_rows(app):
    lc = LecturerCertificate(
        instance_id=None, trainer_id=None, number='TEST-100001',
        recipient_name='Тестовому Тренеру', event_title='Захід',
    )
    assert lc.emailed_at is None


def test_column_exists_and_is_nullable(app):
    col = LecturerCertificate.__table__.c.emailed_at
    assert col.nullable is True
    assert col.index is True
