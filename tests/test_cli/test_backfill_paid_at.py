"""Дозаповнення дати оплати старим реєстраціям: `flask backfill-paid-at`.

До виправлення ручна позначка ставила paid без paid_at. Команда пише
лише явно передані дати (з виписки або логу) і лише з --apply. Запис іде
через ORM: updated_at мусить зрушити, інакше MM Medic, що тягне зміни за
updated_since, нової дати не побачить.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.payment_transaction import PaymentTransaction
from app.models.registration import EventRegistration
from app.models.user import User
from app.utils import ensure_utc, to_kyiv

OLD_UPDATED_AT = datetime(2026, 9, 20, 8, tzinfo=timezone.utc)


@pytest.fixture
def legacy_paid(app):
    """Оплачений рахунок без дати -- як 17 рядків у проді на 07.10.2026."""
    user = User.create_with_password(
        f'bpa-{uuid4().hex[:8]}@test.com', 'password123', first_name='A', last_name='B')
    course = Course(title='Backfill', slug=f'bpa-{uuid4().hex[:8]}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='active', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501112233',
        specialty='S', workplace='W', status='confirmed', payment_status='paid',
        payment_method='invoice', payment_amount=3000,
    )
    db.session.add(reg)
    db.session.flush()
    reg.updated_at = OLD_UPDATED_AT
    db.session.commit()
    return reg


def _run(app, *args):
    return app.test_cli_runner().invoke(args=['backfill-paid-at', *args])


def _reload(reg):
    db.session.expire_all()
    return db.session.get(EventRegistration, reg.id)


def _manual_txns(reg):
    return PaymentTransaction.query.filter_by(
        registration_id=reg.id, source='manual').all()


def test_without_apply_writes_nothing(app, legacy_paid):
    result = _run(app, '--date', f'{legacy_paid.id}=2026-09-15')

    assert result.exit_code == 0, result.output
    assert '2026-09-15' in result.output
    reg = _reload(legacy_paid)
    assert reg.paid_at is None
    assert ensure_utc(reg.updated_at) == OLD_UPDATED_AT
    assert _manual_txns(reg) == []


def test_apply_sets_date_bumps_updated_at_and_logs(app, legacy_paid):
    result = _run(app, '--date', f'{legacy_paid.id}=2026-09-15', '--apply')

    assert result.exit_code == 0, result.output
    reg = _reload(legacy_paid)
    assert to_kyiv(reg.paid_at).date().isoformat() == '2026-09-15'
    assert ensure_utc(reg.updated_at) > OLD_UPDATED_AT
    txns = _manual_txns(reg)
    assert len(txns) == 1
    assert txns[0].raw_payload['actor'] == 'cli:backfill-paid-at'


def test_listing_without_dates_shows_missing(app, legacy_paid):
    result = _run(app)
    assert result.exit_code == 0, result.output
    assert str(legacy_paid.id) in result.output


def test_existing_date_is_not_overwritten(app, legacy_paid):
    legacy_paid.paid_at = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
    db.session.commit()

    _run(app, '--date', f'{legacy_paid.id}=2026-09-15', '--apply')

    reg = _reload(legacy_paid)
    assert to_kyiv(reg.paid_at).date().isoformat() == '2026-09-01'


def test_any_error_aborts_whole_batch(app, legacy_paid):
    future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    result = _run(app, '--date', f'{legacy_paid.id}=2026-09-15',
                  '--date', f'999999999={future}', '--apply')

    assert result.exit_code != 0
    assert _reload(legacy_paid).paid_at is None


def test_malformed_date_is_rejected(app, legacy_paid):
    result = _run(app, '--date', f'{legacy_paid.id}:2026-09-15', '--apply')
    assert result.exit_code != 0
    assert _reload(legacy_paid).paid_at is None
