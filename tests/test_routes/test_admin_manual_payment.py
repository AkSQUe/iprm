"""Ручна позначка оплати з адмінки: дата, журнал і курсор для MM Medic.

Два HTTP-шляхи: випадайка «Оплата» в таблиці реєстрацій (дата -- "зараз")
і форма учасника (дата з виписки). Після позначки рядок мусить приїхати
в MM Medic через `GET /api/v1/registrations?updated_since=...` уже з
paid_at -- інакше фінансовий менеджер не побачить оплату в звіті за місяць.
Саме правило -- tests/test_services/test_manual_payment_status.py.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.payment_transaction import PaymentTransaction
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.utils import to_kyiv
from tests.support.rbac import grant_role

API_KEY = 'test-partner-api-key-manual-payment-0001'


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'mpay-{_uid()}@test.com', 'password123',
        first_name='M', last_name='P', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


@pytest.fixture
def reg(app, admin):
    course = Course(title='Invoice Course', slug=f'mpay-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='active', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    r = EventRegistration(
        user_id=admin.id, instance_id=inst.id, phone='+380501112233',
        specialty='T', workplace='T', status='confirmed', payment_status='unpaid',
        payment_method='invoice', payment_amount=2500,
    )
    db.session.add(r)
    db.session.commit()
    return r


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _manual_txns(reg):
    return PaymentTransaction.query.filter_by(
        registration_id=reg.id, source='manual').all()


def _kyiv_today():
    return to_kyiv(datetime.now(timezone.utc)).date()


class TestInlinePayment:
    def test_paid_sets_date_and_logs_admin(self, client, admin, reg):
        _login(client, admin)
        r = client.post(f'/admin/registrations/{reg.id}/payment',
                        data={'payment': 'paid'},
                        headers={'X-Requested-With': 'XMLHttpRequest',
                                 'Accept': 'application/json'})
        assert r.status_code in (200, 302)

        db.session.expire_all()
        assert reg.payment_status == 'paid'
        assert reg.paid_at is not None
        txns = _manual_txns(reg)
        assert [t.mapped_status for t in txns] == ['paid']
        assert float(txns[0].amount) == 2500.0
        assert txns[0].raw_payload['actor'] == admin.email

    def test_back_to_unpaid_clears_date(self, client, admin, reg):
        _login(client, admin)
        client.post(f'/admin/registrations/{reg.id}/payment', data={'payment': 'paid'})
        client.post(f'/admin/registrations/{reg.id}/payment', data={'payment': 'unpaid'})

        db.session.expire_all()
        assert reg.payment_status == 'unpaid'
        assert reg.paid_at is None
        assert [t.mapped_status for t in _manual_txns(reg)] == ['paid', 'unpaid']


def _participant_form(reg, **over):
    data = {
        'instance_id': str(reg.instance_id),
        'last_name': 'Петренко', 'first_name': 'Іван', 'middle_name': '',
        'email': '', 'phone': '+380501112233',
        'status': 'confirmed', 'payment_status': 'paid', 'paid_on': '',
        'payment_amount': '2500', 'promo_code': '',
        'participation_format': '', 'participant_type': '',
    }
    data.update(over)
    return data


class TestParticipantForm:
    def test_date_from_form_is_saved(self, client, admin, reg):
        _login(client, admin)
        day = _kyiv_today() - timedelta(days=12)
        r = client.post(f'/admin/registrations/{reg.id}/edit',
                        data=_participant_form(reg, paid_on=day.isoformat()))
        assert r.status_code == 302

        db.session.expire_all()
        assert reg.payment_status == 'paid'
        assert to_kyiv(reg.paid_at).date() == day
        assert [t.mapped_status for t in _manual_txns(reg)] == ['paid']

    def test_empty_date_means_now(self, client, admin, reg):
        _login(client, admin)
        r = client.post(f'/admin/registrations/{reg.id}/edit',
                        data=_participant_form(reg))
        assert r.status_code == 302

        db.session.expire_all()
        assert to_kyiv(reg.paid_at).date() == _kyiv_today()

    def test_future_date_is_validation_error(self, client, admin, reg):
        _login(client, admin)
        day = _kyiv_today() + timedelta(days=2)
        r = client.post(f'/admin/registrations/{reg.id}/edit',
                        data=_participant_form(reg, paid_on=day.isoformat()))

        assert r.status_code == 200
        assert 'Дата оплати не може бути в майбутньому' in r.get_data(as_text=True)
        db.session.expire_all()
        assert reg.payment_status == 'unpaid'
        assert reg.paid_at is None

    def test_edit_form_shows_stored_date(self, client, admin, reg):
        reg.payment_status = 'paid'
        reg.set_paid_at(datetime(2026, 9, 10, 9, tzinfo=timezone.utc), 'datetime')
        db.session.commit()
        _login(client, admin)

        html = client.get(f'/admin/registrations/{reg.id}/edit').get_data(as_text=True)
        assert 'value="2026-09-10"' in html


@pytest.fixture
def partner_settings(app):
    s = SiteSettings.get()
    s.partner_integration_enabled = True
    s.partner_api_key = API_KEY
    db.session.commit()
    yield s
    s.partner_integration_enabled = False
    s.partner_api_key = ''
    db.session.commit()


def test_marked_row_reaches_partner_cursor_with_date(client, admin, reg,
                                                     partner_settings):
    """MM Medic тягне зміни за updated_since: позначка мусить оновити
    updated_at, і рядок приїде вже з датою оплати."""
    reg.updated_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.session.commit()
    cursor = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
        '%Y-%m-%dT%H:%M:%SZ')

    def _row():
        data = client.get(f'/api/v1/registrations?per_page=200&updated_since={cursor}',
                          headers={'X-API-Key': API_KEY}).get_json()
        return next((i for i in data['items'] if i['id'] == reg.id), None)

    assert _row() is None

    _login(client, admin)
    client.post(f'/admin/registrations/{reg.id}/payment', data={'payment': 'paid'})

    row = _row()
    assert row is not None
    assert row['payment_status'] == 'paid'
    assert row['paid_at'] is not None
    assert row['paid_at_precision'] == 'datetime'
