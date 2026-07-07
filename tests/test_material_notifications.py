"""Tests for MM Medic material reservation email notifications (IPRM side)."""
from datetime import datetime, timedelta, timezone

from flask import render_template

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.models.email_log import EmailLog
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem, MaterialReservationStatus,
)
from app.models.site_settings import SiteSettings


def _make_instance(trainer_email='trainer@example.com', ended=False, slug_suffix='n'):
    trainer = Trainer(full_name='Іван Тренер', slug=f'trainer-{slug_suffix}', email=trainer_email)
    db.session.add(trainer)
    course = Course(title='Плазмотерапія', slug=f'course-{slug_suffix}', trainer=trainer)
    db.session.add(course)
    db.session.flush()
    now = datetime.now(timezone.utc)
    inst = CourseInstance(
        course_id=course.id, trainer_id=trainer.id,
        start_date=now - timedelta(days=2) if ended else now + timedelta(days=2),
        end_date=now - timedelta(days=1) if ended else now + timedelta(days=3),
        location='Київ',
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _make_reservation(inst, status=MaterialReservationStatus.RESERVED, slug_suffix='n'):
    res = MaterialReservation(instance_id=inst.id, external_ref=f'iprm-instance-{inst.id}', status=status)
    db.session.add(res)
    db.session.flush()
    res.items.append(MaterialReservationItem(sku='NDL-21', name='Голка 21G', quantity_reserved=5))
    db.session.flush()
    return res


# ----------------------------- template rendering -----------------------------

def test_materials_reserved_template_renders(app):
    with app.app_context():
        item = MaterialReservationItem(sku='NDL-21', name='Голка 21G', quantity_reserved=5)
        html = render_template(
            'emails/materials_reserved.html',
            site_settings=SiteSettings.get(),
            event_title='Плазмотерапія', event_date='01.01.2026', event_location='Київ',
            trainer_name='Іван', items=[item],
        )
        assert 'Голка 21G' in html and 'NDL-21' in html and 'Плазмотерапія' in html


def test_materials_reminder_template_renders(app):
    with app.app_context():
        item = MaterialReservationItem(sku='NDL-21', name='Голка 21G', quantity_reserved=5)
        html = render_template(
            'emails/materials_actuals_reminder.html',
            site_settings=SiteSettings.get(),
            event_title='Плазмотерапія', event_date='01.01.2026',
            items=[item], admin_url='https://plasma-regen.com/admin/instances/1/materials',
        )
        assert 'Внесіть фактичні' in html and 'instances/1/materials' in html


# ----------------------------- trigger + senders -----------------------------

def test_materials_trigger_allowed():
    assert EmailLog.is_valid_trigger('materials')


def test_send_materials_reserved_targets_trainer(app, monkeypatch):
    from app.services.email_service import EmailService
    captured = {}
    monkeypatch.setattr(EmailService, 'send_email',
                        staticmethod(lambda **kw: captured.update(kw) or 'log'))
    inst = _make_instance(slug_suffix='r1')
    res = _make_reservation(inst, slug_suffix='r1')
    EmailService.send_materials_reserved(res, inst)
    assert captured.get('to') == 'trainer@example.com'
    assert captured.get('template_name') == 'materials_reserved'
    assert captured.get('trigger') == 'materials'


def test_send_materials_reserved_skips_without_trainer_email(app, monkeypatch):
    from app.services.email_service import EmailService
    calls = []
    monkeypatch.setattr(EmailService, 'send_email', staticmethod(lambda **kw: calls.append(kw)))
    inst = _make_instance(trainer_email=None, slug_suffix='r2')
    res = _make_reservation(inst, slug_suffix='r2')
    assert EmailService.send_materials_reserved(res, inst) is None
    assert not calls


def test_actuals_reminder_is_idempotent(app, monkeypatch):
    from app.services import material_reservation_service as mrs
    from app.services.email_service import EmailService

    monkeypatch.setattr(mrs, 'get_client', lambda: object())  # avoid MMConfigError
    sent = []

    def _fake_reminder(r, i):
        sent.append(r.external_ref)
        return ['admin@example.com']  # non-empty -> recipients attempted

    monkeypatch.setattr(EmailService, 'send_materials_actuals_reminder',
                        staticmethod(_fake_reminder))

    inst = _make_instance(ended=True, slug_suffix='rem')
    res = _make_reservation(inst, slug_suffix='rem')

    n1 = mrs.send_pending_actuals_reminders()
    assert n1 == 1 and sent == [res.external_ref]
    assert res.actuals_reminder_sent_at is not None

    n2 = mrs.send_pending_actuals_reminders()
    assert n2 == 0  # flag set -> not re-sent


def test_actuals_reminder_not_marked_without_recipients(app, monkeypatch):
    from app.services import material_reservation_service as mrs
    from app.services.email_service import EmailService

    monkeypatch.setattr(mrs, 'get_client', lambda: object())
    monkeypatch.setattr(EmailService, 'send_materials_actuals_reminder',
                        staticmethod(lambda r, i: []))  # no recipients

    inst = _make_instance(ended=True, slug_suffix='norcpt')
    res = _make_reservation(inst, slug_suffix='norcpt')

    n = mrs.send_pending_actuals_reminders()
    assert n == 0
    assert res.actuals_reminder_sent_at is None  # left NULL -> retried later
