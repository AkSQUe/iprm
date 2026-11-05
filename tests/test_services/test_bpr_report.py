"""Подача звіту до Центру тестування: масовий перехід «Підтверджено» ->
«Завершено» без листів і партнерських подій, і скасування подачі."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import bpr_report, partner_events
from app.services.bpr_report import ReportError, is_closed, submit_report, undo_report


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'adm-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Адмін', last_name='Адмінов', email_confirmed=True,
    )
    db.session.flush()
    return user


def _instance(days_ago=None, days_ahead=None, with_end=False):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'bpr-{uuid4().hex[:6]}',
        is_active=True, event_type='course',
    )
    db.session.add(course)
    db.session.flush()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_ago) if days_ago else now + timedelta(days=days_ahead)
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ', start_date=start,
        end_date=(start + timedelta(hours=4)) if with_end else None,
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _reg(instance, status):
    user = User.create_with_password(
        f'bpr-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True,
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status=status,
        payment_status='paid',
    )
    db.session.add(reg)
    db.session.flush()
    return reg


@pytest.fixture
def instance_past(app):
    inst = _instance(days_ago=10)
    db.session.commit()
    return inst


@pytest.fixture
def instance_future(app):
    inst = _instance(days_ahead=10)
    db.session.commit()
    return inst


@pytest.fixture
def regs(instance_past):
    rows = [_reg(instance_past, s) for s in
            ('confirmed', 'pending', 'cancelled', 'completed')]
    db.session.commit()
    return rows


@pytest.fixture
def mail_calls(monkeypatch):
    from app.services.email_service import EmailService
    calls = []
    monkeypatch.setattr(
        EmailService, 'send_status_change',
        staticmethod(lambda *a, **kw: calls.append((a, kw))),
    )
    return calls


@pytest.fixture
def partner_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(partner_events, '_queue', lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(partner_events, 'emit', lambda *a, **kw: calls.append(a))
    return calls


def test_submit_moves_only_confirmed(instance_past, regs, admin):
    moved = submit_report(instance_past, date(2026, 11, 20), admin)
    assert moved == 1
    assert [r.status for r in regs] == ['completed', 'pending', 'cancelled', 'completed']
    assert [r.completed_by_report for r in regs] == [True, False, False, False]
    assert instance_past.bpr_report_submitted_on == date(2026, 11, 20)
    assert instance_past.bpr_report_submitted_by_id == admin.id
    assert is_closed(instance_past) is True


def test_submit_sends_no_mail_and_no_partner_events(
        instance_past, regs, admin, mail_calls, partner_calls):
    submit_report(instance_past, date(2026, 11, 20), admin)
    assert mail_calls == []
    assert partner_calls == []


def test_submit_future_event_refused(instance_future, admin):
    with pytest.raises(ReportError):
        submit_report(instance_future, date(2026, 11, 20), admin)
    assert instance_future.bpr_report_submitted_on is None


def test_submit_uses_end_date_when_present(app, admin):
    inst = _instance(days_ago=1, with_end=False)
    inst.end_date = datetime.now(timezone.utc) + timedelta(days=2)
    db.session.commit()
    with pytest.raises(ReportError):
        submit_report(inst, date(2026, 11, 20), admin)


def test_submit_without_dates_refused(app, admin):
    inst = _instance(days_ago=1)
    inst.start_date = None
    db.session.commit()
    with pytest.raises(ReportError):
        submit_report(inst, date(2026, 11, 20), admin)


def test_second_submit_is_noop(instance_past, regs, admin):
    submit_report(instance_past, date(2026, 11, 20), admin)
    assert submit_report(instance_past, date(2026, 11, 21), admin) == 0
    assert instance_past.bpr_report_submitted_on == date(2026, 11, 20)


def test_undo_returns_only_moved(instance_past, regs, admin):
    submit_report(instance_past, date(2026, 11, 20), admin)
    assert undo_report(instance_past, admin) == 1
    assert regs[0].status == 'confirmed' and regs[3].status == 'completed'
    assert [r.completed_by_report for r in regs] == [False] * 4
    assert instance_past.bpr_report_submitted_on is None
    assert instance_past.bpr_report_submitted_by_id is None
    assert is_closed(instance_past) is False


def test_undo_keeps_manual_attendance(instance_past, regs, admin):
    submit_report(instance_past, date(2026, 11, 20), admin)
    regs[0].attended = True
    db.session.commit()
    undo_report(instance_past, admin)
    assert regs[0].status == 'completed' and regs[0].completed_by_report is False


def test_undo_without_submission_is_noop(instance_past, regs, admin):
    assert undo_report(instance_past, admin) == 0
    assert regs[0].status == 'confirmed'


def test_is_closed_none():
    assert is_closed(None) is False


def test_module_exports_audit_logger():
    assert bpr_report.audit_logger.name == 'audit'
