"""Tests for MM Medic material reservation email notifications (IPRM side)."""
import hashlib
import hmac
import json
import time
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


# ----------------------------- reverse status webhook (MM Medic -> IPRM) -----------------------------

_MM_SECRET = 'reverse-webhook-secret'


def _enable_mm():
    site = SiteSettings.get()
    site.mm_medic_integration_enabled = True
    site.partner_webhook_secret = _MM_SECRET
    db.session.commit()


def _mm_headers(body, ts=None, bad=False):
    ts = ts or str(int(time.time()))
    sig = 'deadbeef' if bad else hmac.new(_MM_SECRET.encode(), ts.encode() + b'.' + body, hashlib.sha256).hexdigest()
    return {'X-IPRM-Signature': sig, 'X-IPRM-Timestamp': ts, 'Content-Type': 'application/json'}


def test_mm_status_webhook_marks_consumed_and_actuals(app, client):
    _enable_mm()
    inst = _make_instance(slug_suffix='mmw1')
    res = _make_reservation(inst, slug_suffix='mmw1')
    body = json.dumps({'external_ref': res.external_ref, 'status': 'consumed',
                       'items': [{'sku': 'NDL-21', 'quantity': 4}]}).encode()
    r = client.post('/api/partner/mm-medic/reservation-status', data=body, headers=_mm_headers(body))
    assert r.status_code == 200
    fresh = MaterialReservation.query.get(res.id)
    assert fresh.status == MaterialReservationStatus.CONSUMED
    assert fresh.items[0].quantity_actual == 4


def test_mm_status_webhook_marks_expired(app, client):
    _enable_mm()
    inst = _make_instance(slug_suffix='mmw2')
    res = _make_reservation(inst, slug_suffix='mmw2')
    body = json.dumps({'external_ref': res.external_ref, 'status': 'expired', 'items': []}).encode()
    r = client.post('/api/partner/mm-medic/reservation-status', data=body, headers=_mm_headers(body))
    assert r.status_code == 200
    assert MaterialReservation.query.get(res.id).status == MaterialReservationStatus.EXPIRED


def test_mm_status_webhook_rejects_bad_signature(app, client):
    _enable_mm()
    inst = _make_instance(slug_suffix='mmw3')
    res = _make_reservation(inst, slug_suffix='mmw3')
    body = json.dumps({'external_ref': res.external_ref, 'status': 'cancelled'}).encode()
    r = client.post('/api/partner/mm-medic/reservation-status', data=body, headers=_mm_headers(body, bad=True))
    assert r.status_code == 401
    assert MaterialReservation.query.get(res.id).status == MaterialReservationStatus.RESERVED


def test_mm_status_webhook_unknown_ref_acked(app, client):
    _enable_mm()
    body = json.dumps({'external_ref': 'iprm-instance-999999', 'status': 'consumed'}).encode()
    r = client.post('/api/partner/mm-medic/reservation-status', data=body, headers=_mm_headers(body))
    assert r.status_code == 200


# ----------------------------- trainer public view + overview export -----------------------------

def test_trainer_materials_public_view(app, client):
    from app.services import material_reservation_service as mrs
    inst = _make_instance(slug_suffix='trn')
    res = _make_reservation(inst, slug_suffix='trn')
    with app.app_context():
        token = mrs.make_trainer_token(inst.id)
    r = client.get(f'/materials/{token}')
    assert r.status_code == 200
    assert b'NDL-21' in r.data
    # tampered token -> 404
    assert client.get('/materials/not-a-real-token').status_code == 404


def test_overview_export_xlsx_bytes(app):
    from app.services import xlsx_io
    with app.app_context():
        inst = _make_instance(slug_suffix='exp')
        res = _make_reservation(inst, slug_suffix='exp')
        bio = xlsx_io.export_material_reservations_xlsx([res])
        data = bio.getvalue()
        assert data[:2] == b'PK'  # xlsx is a zip
