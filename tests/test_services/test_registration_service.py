"""Tests for app.services.registration_service (Course+CourseInstance era)."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import registration_service


@pytest.fixture
def user(app):
    u = User(email=f'reg-{uuid4().hex[:6]}@test.com', first_name='Reg', last_name='User')
    u.set_password('password123')
    db.session.add(u)
    db.session.flush()
    return u


def _make_course_instance(course_kwargs, instance_kwargs):
    course = Course(slug=f'evt-{uuid4().hex[:6]}', is_active=True, **course_kwargs)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='active', **instance_kwargs)
    db.session.add(inst)
    db.session.flush()
    return inst


@pytest.fixture
def free_instance(app):
    return _make_course_instance(
        {'title': 'Free Event', 'base_price': 0},
        {'event_format': 'offline', 'price': 0},
    )


@pytest.fixture
def paid_instance(app):
    return _make_course_instance(
        {'title': 'Paid Event', 'base_price': 5000, 'max_participants': 2},
        {'event_format': 'offline', 'price': 5000, 'max_participants': 2},
    )


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
    def test_no_existing(self, app, user, free_instance):
        result = registration_service.find_existing(user.id, free_instance.id)
        assert result is None

    def test_finds_existing(self, app, user, free_instance):
        reg = EventRegistration(
            user_id=user.id, instance_id=free_instance.id,
            phone='+380000', specialty='Test', workplace='Test',
            status='confirmed', payment_status='paid',
        )
        db.session.add(reg)
        db.session.flush()

        result = registration_service.find_existing(user.id, free_instance.id)
        assert result is not None
        assert result.id == reg.id


class TestCheckCapacity:
    def test_unlimited_capacity(self, app, free_instance):
        has, _ = registration_service.check_capacity(free_instance.id)
        assert has is True

    def test_has_capacity(self, app, paid_instance):
        has, _ = registration_service.check_capacity(paid_instance.id)
        assert has is True

    def test_full_capacity(self, app, user, paid_instance):
        for i in range(2):
            u = User(email=f'fill-{uuid4().hex[:6]}@test.com', first_name='Fill', last_name=str(i))
            u.set_password('pass')
            db.session.add(u)
            db.session.flush()
            reg = EventRegistration(
                user_id=u.id, instance_id=paid_instance.id,
                phone='+380000', specialty='Test', workplace='Test',
                status='confirmed', payment_status='paid',
            )
            db.session.add(reg)
        db.session.flush()

        has, _ = registration_service.check_capacity(paid_instance.id)
        assert has is False


class TestCreateOrReactivate:
    def test_create_free_registration(self, app, user, free_instance, form_data):
        reg, is_free = registration_service.create_or_reactivate(
            user.id, free_instance, form_data,
        )
        assert is_free is True
        assert reg.status == 'confirmed'
        assert reg.payment_status == 'paid'
        assert reg.phone == '+380501234567'

    def test_create_paid_registration(self, app, user, paid_instance, form_data):
        reg, is_free = registration_service.create_or_reactivate(
            user.id, paid_instance, form_data,
        )
        assert is_free is False
        assert reg.status == 'pending'
        assert reg.payment_status == 'unpaid'
        assert reg.payment_amount == 5000

    def test_reactivate_cancelled(self, app, user, free_instance, form_data):
        cancelled = EventRegistration(
            user_id=user.id, instance_id=free_instance.id,
            phone='+380old', specialty='Old', workplace='Old',
            status='cancelled', payment_status='unpaid',
        )
        db.session.add(cancelled)
        db.session.flush()

        reg, is_free = registration_service.create_or_reactivate(
            user.id, free_instance, form_data, existing=cancelled,
        )
        assert reg.id == cancelled.id
        assert reg.status == 'confirmed'
        assert reg.phone == '+380501234567'
