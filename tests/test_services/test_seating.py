"""Місткість заходу: місце тримає лише оплачена реєстрація.

Захисні гарантії для рішення 12.08.2026 (app/services/seating.py): раніше
неоплачений `pending` блокував продаж безстроково, а перевищення пулу ніде
не було видно.
"""
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import registration_service, seating
from app.services.course_listing import capacity_map


@pytest.fixture
def instance(app):
    course = Course(
        slug=f'seat-{uuid4().hex[:6]}', title='Seat Event',
        is_active=True, base_price=5000, max_participants=2,
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        price=5000, max_participants=2,
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _register(instance, status='pending', payment_status='unpaid'):
    user = User.create_with_password(
        f'seat-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Seat', last_name='User',
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id,
        phone='+380501234567', specialty='Test', workplace='Test',
        status=status, payment_status=payment_status,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


class TestOccupancy:
    def test_unpaid_pending_does_not_occupy(self, app, instance):
        _register(instance, status='pending', payment_status='unpaid')
        _register(instance, status='pending', payment_status='unpaid')

        assert seating.occupied_count(instance.id) == 0
        assert instance.has_capacity is True
        assert registration_service.check_capacity(instance.id)[0] is True

    def test_confirmed_but_unpaid_does_not_occupy(self, app, instance):
        """Підтверджена менеджером, але неоплачена -- теж не тримає місце."""
        _register(instance, status='confirmed', payment_status='unpaid')

        assert seating.occupied_count(instance.id) == 0

    def test_paid_occupies(self, app, instance):
        _register(instance, status='confirmed', payment_status='paid')

        assert seating.occupied_count(instance.id) == 1
        assert instance.has_capacity is True

    def test_cancelled_paid_does_not_occupy(self, app, instance):
        """Повернення коштів приходить у парі зі status='cancelled'."""
        _register(instance, status='cancelled', payment_status='refunded')
        _register(instance, status='cancelled', payment_status='paid')

        assert seating.occupied_count(instance.id) == 0

    def test_full_when_paid_reach_capacity(self, app, instance):
        _register(instance, status='confirmed', payment_status='paid')
        _register(instance, status='confirmed', payment_status='paid')

        assert instance.has_capacity is False
        assert registration_service.check_capacity(instance.id)[0] is False

    def test_public_capacity_map_ignores_unpaid(self, app, instance):
        _register(instance, status='pending', payment_status='unpaid')
        _register(instance, status='confirmed', payment_status='paid')

        assert capacity_map([instance.course_id])[instance.id] == 1


class TestOverbooking:
    def test_not_overbooked_at_capacity(self, app, instance):
        for _ in range(2):
            _register(instance, status='confirmed', payment_status='paid')

        assert instance.is_overbooked is False
        assert seating.is_overbooked(2, 2) is False

    def test_overbooked_beyond_capacity(self, app, instance):
        for _ in range(3):
            _register(instance, status='confirmed', payment_status='paid')

        assert instance.is_overbooked is True
        assert seating.seats_left(2, 3) == 0

    def test_unlimited_capacity_never_overbooked(self, app, instance):
        instance.max_participants = None
        instance.course.max_participants = None
        db.session.flush()
        _register(instance, status='confirmed', payment_status='paid')

        assert instance.is_overbooked is False
        assert seating.seats_left(None, 5) is None

    def test_notify_sent_when_pool_exceeded(self, app, instance):
        for _ in range(2):
            _register(instance, status='confirmed', payment_status='paid')
        reg = _register(instance, status='confirmed', payment_status='paid')

        with patch('app.services.email_service.EmailService.notify_overbooking') as mock:
            assert seating.notify_overbooking_if_needed(reg) is True
        mock.assert_called_once()
        assert mock.call_args.kwargs['occupied'] == 3
        assert mock.call_args.kwargs['capacity'] == 2

    def test_no_notify_within_capacity(self, app, instance):
        reg = _register(instance, status='confirmed', payment_status='paid')

        with patch('app.services.email_service.EmailService.notify_overbooking') as mock:
            assert seating.notify_overbooking_if_needed(reg) is False
        mock.assert_not_called()

    def test_notify_failure_does_not_raise(self, app, instance):
        """Збій розсилки не має чіпати оплату -- гроші вже списані."""
        for _ in range(3):
            _register(instance, status='confirmed', payment_status='paid')
        reg = instance.registrations.first()

        with patch(
            'app.services.email_service.EmailService.notify_overbooking',
            side_effect=RuntimeError('smtp down'),
        ):
            assert seating.notify_overbooking_if_needed(reg) is False
