"""Ендпоінт POST /api/partner/mm-medic/bank-payment."""
import hashlib
import hmac
import json
import time
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User

URL = '/api/partner/mm-medic/bank-payment'
SECRET = 'bank-webhook-secret'


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def mm_enabled(app):
    site = SiteSettings.get()
    site.mm_medic_integration_enabled = True
    site.partner_webhook_secret = SECRET
    db.session.commit()


@pytest.fixture
def reg_unpaid_1500(app):
    user = User.create_with_password(
        f'bankapi-{_uid()}@test.com', 'password123', first_name='T', last_name='U',
    )
    db.session.flush()
    course = Course(title='C', slug=f'bankapi-{_uid()}', event_type='course',
                    base_price=1500, is_active=True, created_by=user.id)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='active',
                          event_format='offline', price=1500)
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380000000000',
        specialty='T', workplace='T', status='pending',
        payment_status='unpaid', payment_amount=Decimal('1500.00'),
    )
    db.session.add(reg)
    db.session.commit()
    return reg


@pytest.fixture(autouse=True)
def no_mail(monkeypatch):
    from app.services.email_service import EmailService
    monkeypatch.setattr(EmailService, 'send_payment_confirmation',
                        staticmethod(lambda registration: None))


@pytest.fixture
def signed(client):
    def post(url, payload, ts=None, bad=False):
        body = json.dumps(payload).encode()
        ts = str(ts if ts is not None else int(time.time()))
        sig = 'deadbeef' if bad else hmac.new(
            SECRET.encode(), ts.encode() + b'.' + body, hashlib.sha256).hexdigest()
        return client.post(url, data=body, headers={
            'X-IPRM-Signature': sig, 'X-IPRM-Timestamp': ts,
            'Content-Type': 'application/json'})
    return post


def _payload(reg, **over):
    data = {'order_ref': f'REG-{reg.id}', 'amount': '1500.00',
            'transacted_at': '2026-10-30T09:15:00+00:00',
            'bank_tx_ref': f'mm-bt-{_uid()}', 'actor': 'manager@mm-medic.com'}
    data.update(over)
    return data


def test_valid_request_confirms(client, signed, mm_enabled, reg_unpaid_1500):
    resp = signed(URL, _payload(reg_unpaid_1500))
    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'paid', 'reason': None,
                               'order_ref': f'REG-{reg_unpaid_1500.id}'}
    db.session.refresh(reg_unpaid_1500)
    assert reg_unpaid_1500.payment_status == 'paid'


def test_business_refusal_is_200(client, signed, mm_enabled, reg_unpaid_1500):
    reg_unpaid_1500.payment_status = 'paid'
    db.session.commit()
    resp = signed(URL, _payload(reg_unpaid_1500))
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'refused'
    assert resp.get_json()['reason'] == 'already_paid'


def test_session_is_closed_after_refusal(client, signed, mm_enabled,
                                         reg_unpaid_1500, monkeypatch):
    """Ранні відмови не відкочують сесію самі, тож це робить ендпоінт: інакше
    FOR UPDATE тримався б до кінця запиту."""
    reg_unpaid_1500.payment_status = 'paid'
    db.session.commit()
    calls = []
    real = db.session.rollback
    monkeypatch.setattr(db.session, 'rollback',
                        lambda: (calls.append(1), real())[1])
    signed(URL, _payload(reg_unpaid_1500))
    assert calls


def test_bad_signature_401(client, signed, mm_enabled, reg_unpaid_1500):
    resp = signed(URL, _payload(reg_unpaid_1500), bad=True)
    assert resp.status_code == 401
    assert resp.get_json() == {'status': 'invalid_signature'}
    db.session.refresh(reg_unpaid_1500)
    assert reg_unpaid_1500.payment_status == 'unpaid'


def test_stale_timestamp_401(client, signed, mm_enabled, reg_unpaid_1500):
    resp = signed(URL, _payload(reg_unpaid_1500), ts=int(time.time()) - 301)
    assert resp.status_code == 401
    assert resp.get_json() == {'status': 'stale'}


def test_missing_field_400(client, signed, mm_enabled, reg_unpaid_1500):
    data = _payload(reg_unpaid_1500)
    del data['bank_tx_ref']
    resp = signed(URL, data)
    assert resp.status_code == 400
    assert resp.get_json() == {'status': 'malformed', 'field': 'bank_tx_ref'}


@pytest.mark.parametrize('field,value', [
    ('amount', 'abc'), ('amount', '-5'), ('transacted_at', 'yesterday'),
])
def test_unparsable_field_400(client, signed, mm_enabled, reg_unpaid_1500,
                              field, value):
    resp = signed(URL, _payload(reg_unpaid_1500, **{field: value}))
    assert resp.status_code == 400
    assert resp.get_json() == {'status': 'malformed', 'field': field}


def test_integration_disabled_404(client, signed, app, reg_unpaid_1500):
    site = SiteSettings.get()
    site.mm_medic_integration_enabled = False
    db.session.commit()
    resp = signed(URL, _payload(reg_unpaid_1500))
    assert resp.status_code == 404
    assert resp.get_json() == {'status': 'disabled'}


def test_reservation_status_still_verifies(client, signed, mm_enabled):
    body = {'external_ref': 'x', 'status': 'approved'}
    bad = signed('/api/partner/mm-medic/reservation-status', body, bad=True)
    assert bad.status_code == 401
    ok = signed('/api/partner/mm-medic/reservation-status', body)
    assert ok.status_code == 200
    assert ok.get_json()['status'] == 'unknown_ref'
