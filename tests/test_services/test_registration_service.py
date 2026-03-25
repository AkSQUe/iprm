"""Tests for app.services.registration_service."""
import pytest
from uuid import uuid4
from app.extensions import db
from app.models.user import User
from app.models.event import Event
from app.models.registration import EventRegistration
from app.services import registration_service


@pytest.fixture
def user(app):
    from uuid import uuid4
    u = User(email=f'reg-{uuid4().hex[:6]}@test.com', first_name='Reg', last_name='User')
    u.set_password('password123')
    db.session.add(u)
    db.session.flush()
    return u


@pytest.fixture
def free_event(app, user):
    e = Event(
        title='Free Event', slug=f'free-evt-{uuid4().hex[:6]}',
        event_type='course', event_format='offline', status='active',
        price=0, is_active=True, created_by=user.id,
    )
    db.session.add(e)
    db.session.flush()
    return e


@pytest.fixture
def paid_event(app, user):
    e = Event(
        title='Paid Event', slug=f'paid-evt-{uuid4().hex[:6]}',
        event_type='course', event_format='offline', status='active',
        price=5000, max_participants=2, is_active=True, created_by=user.id,
    )
    db.session.add(e)
    db.session.flush()
    return e


@pytest.fixture
def form_data():
    return {
        'phone': '+380501234567',
        'specialty': 'Dermatologist',
        'workplace': 'City Hospital',
        'experience_years': 5,
        'license_number': 'LIC-001',
    }


class TestFindExisting:
    def test_no_existing(self, app, user, free_event):
        result = registration_service.find_existing(user.id, free_event.id)
        assert result is None

    def test_finds_existing(self, app, user, free_event):
        reg = EventRegistration(
            user_id=user.id, event_id=free_event.id,
            phone='+380000', specialty='Test', workplace='Test',
            status='confirmed', payment_status='paid',
        )
        db.session.add(reg)
        db.session.flush()

        result = registration_service.find_existing(user.id, free_event.id)
        assert result is not None
        assert result.id == reg.id


class TestCheckCapacity:
    def test_unlimited_capacity(self, app, free_event):
        has, _ = registration_service.check_capacity(free_event.id)
        assert has is True

    def test_has_capacity(self, app, paid_event):
        has, _ = registration_service.check_capacity(paid_event.id)
        assert has is True

    def test_full_capacity(self, app, user, paid_event):
        for i in range(2):
            from uuid import uuid4 as _u4
            u = User(email=f'fill-{_u4().hex[:6]}@test.com', first_name='Fill', last_name=str(i))
            u.set_password('pass')
            db.session.add(u)
            db.session.flush()
            reg = EventRegistration(
                user_id=u.id, event_id=paid_event.id,
                phone='+380000', specialty='Test', workplace='Test',
                status='confirmed', payment_status='paid',
            )
            db.session.add(reg)
        db.session.flush()

        has, _ = registration_service.check_capacity(paid_event.id)
        assert has is False


class TestCreateOrReactivate:
    def test_create_free_registration(self, app, user, free_event, form_data):
        reg, is_free = registration_service.create_or_reactivate(
            user.id, free_event, form_data,
        )
        assert is_free is True
        assert reg.status == 'confirmed'
        assert reg.payment_status == 'paid'
        assert reg.phone == '+380501234567'

    def test_create_paid_registration(self, app, user, paid_event, form_data):
        reg, is_free = registration_service.create_or_reactivate(
            user.id, paid_event, form_data,
        )
        assert is_free is False
        assert reg.status == 'pending'
        assert reg.payment_status == 'unpaid'
        assert reg.payment_amount == 5000

    def test_reactivate_cancelled(self, app, user, free_event, form_data):
        cancelled = EventRegistration(
            user_id=user.id, event_id=free_event.id,
            phone='+380old', specialty='Old', workplace='Old',
            status='cancelled', payment_status='unpaid',
        )
        db.session.add(cancelled)
        db.session.flush()

        reg, is_free = registration_service.create_or_reactivate(
            user.id, free_event, form_data, existing=cancelled,
        )
        assert reg.id == cancelled.id
        assert reg.status == 'confirmed'
        assert reg.phone == '+380501234567'
