"""Tests for app.services.payment_ops -- payment state machine."""
from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from app.services.payment_ops import ALLOWED_TRANSITIONS, PaymentOps, STATUS_MAP


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def user(app):
    u = User.create_with_password(
        f'pay-{_uid()}@test.com', 'password123', first_name='Test', last_name='User',
    )
    db.session.flush()
    return u


@pytest.fixture
def instance(app, user):
    c = Course(
        title='Test Course', slug=f'test-course-{_uid()}',
        event_type='course', base_price=1000, is_active=True,
        created_by=user.id,
    )
    db.session.add(c)
    db.session.flush()
    inst = CourseInstance(
        course_id=c.id, status='active', event_format='offline', price=1000,
    )
    db.session.add(inst)
    db.session.flush()
    return inst


@pytest.fixture
def registration(app, user, instance):
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id,
        phone='+380000000000', specialty='Test', workplace='Test',
        status='pending', payment_status='unpaid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


@pytest.fixture
def mock_liqpay():
    service = MagicMock()
    service.validate_callback_signature.return_value = True
    service.is_configured = True
    return service


@pytest.fixture
def ops(mock_liqpay):
    return PaymentOps(mock_liqpay)


class TestStatusMap:
    def test_success_maps_to_paid(self):
        assert STATUS_MAP['success'] == 'paid'

    def test_sandbox_maps_to_paid(self):
        assert STATUS_MAP['sandbox'] == 'paid'

    def test_failure_maps_to_unpaid(self):
        assert STATUS_MAP['failure'] == 'unpaid'

    def test_reversed_maps_to_refunded(self):
        assert STATUS_MAP['reversed'] == 'refunded'


class TestAllowedTransitions:
    def test_unpaid_can_go_to_paid(self):
        assert 'paid' in ALLOWED_TRANSITIONS['unpaid']

    def test_paid_can_go_to_refunded(self):
        assert 'refunded' in ALLOWED_TRANSITIONS['paid']

    def test_refunded_cannot_go_anywhere(self):
        assert len(ALLOWED_TRANSITIONS['refunded']) == 0

    def test_paid_cannot_go_to_unpaid(self):
        assert 'unpaid' not in ALLOWED_TRANSITIONS['paid']


class TestUpdatePaymentStatus:
    def test_unpaid_to_paid(self, ops, registration):
        ok, msg = ops.update_payment_status(registration, 'paid', 'PAY-123', amount=1000)
        assert ok
        assert msg == 'ok'
        assert registration.payment_status == 'paid'
        assert registration.status == 'confirmed'
        assert registration.payment_id == 'PAY-123'
        assert registration.paid_at is not None

    def test_paid_to_refunded(self, ops, registration):
        registration.payment_status = 'paid'
        registration.status = 'confirmed'
        db.session.flush()
        ok, msg = ops.update_payment_status(registration, 'refunded')
        assert ok
        assert registration.payment_status == 'refunded'
        assert registration.status == 'cancelled'

    def test_invalid_transition_is_noop(self, ops, registration):
        registration.payment_status = 'refunded'
        db.session.flush()
        ok, msg = ops.update_payment_status(registration, 'paid')
        assert ok
        assert msg == 'no-op transition'

    def test_amount_mismatch_rejected(self, ops, registration):
        ok, msg = ops.update_payment_status(registration, 'paid', 'PAY-X', amount=500)
        assert not ok
        assert msg == 'amount mismatch'


class TestProcessCallback:
    def test_invalid_signature_rejected(self, ops, mock_liqpay):
        mock_liqpay.validate_callback_signature.return_value = False
        ok, msg = ops.process_callback('data', 'sig')
        assert not ok
        assert msg == 'invalid signature'

    def test_unknown_order_id_rejected(self, ops, mock_liqpay):
        mock_liqpay.decode_callback.return_value = {'order_id': 'UNKNOWN-1', 'status': 'success'}
        ok, msg = ops.process_callback('data', 'sig')
        assert not ok
        assert msg == 'unknown order_id'

    def test_successful_payment(self, ops, mock_liqpay, registration):
        mock_liqpay.decode_callback.return_value = {
            'order_id': f'REG-{registration.id}',
            'status': 'success',
            'payment_id': f'PAY-{_uid()}',
            'amount': 1000,
        }
        ok, msg = ops.process_callback('data', 'sig')
        assert ok
        assert registration.payment_status == 'paid'

    def test_idempotent_duplicate(self, ops, mock_liqpay, registration):
        pid = f'PAY-DUP-{_uid()}'
        registration.payment_status = 'paid'
        registration.payment_id = pid
        db.session.flush()
        mock_liqpay.decode_callback.return_value = {
            'order_id': f'REG-{registration.id}',
            'status': 'success',
            'payment_id': pid,
        }
        ok, msg = ops.process_callback('data', 'sig')
        assert ok
        assert msg == 'already processed'


def _pending_reg(instance, amount=1000):
    """Реєстрація, що зависла в 'pending'.

    Свій користувач на кожну: `(user_id, instance_id)` унікальні, тож два
    зависли платежі на одному заході -- це неодмінно двоє різних людей.
    """
    buyer = User.create_with_password(
        f'pay-{_uid()}@test.com', 'password123',
        first_name='Test', last_name='User',
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=buyer.id, instance_id=instance.id,
        phone='+380000000000', specialty='Test', workplace='Test',
        status='pending', payment_status='pending', payment_amount=amount,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


@pytest.fixture
def pending_enrollment(app, user):
    """Замовлення онлайн-курсу, що зависло в 'pending'."""
    from app.models.online_course import OnlineCourse
    from app.models.online_enrollment import OnlineEnrollment

    course = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Online', slug=f'online-{_uid()}', price=500,
    )
    db.session.add(course)
    db.session.flush()
    item = OnlineEnrollment(
        user_id=user.id, online_course_id=course.id,
        payment_status='pending', payment_amount=500,
    )
    db.session.add(item)
    db.session.flush()
    return item


class TestReconcilePending:
    """Ручна звірка: перепитати LiqPay про платежі, що зависли в 'pending'.

    Потрібна саме окрема вибірка, а не полагодження колбека: колбек, який
    не дійшов, ніхто не перезапитує, а `check_and_update` живе лише на
    сторінках, куди має зайти сам платник.
    """

    def test_picks_only_pending(self, mock_liqpay, user, instance, registration):
        """`unpaid` не чіпаємо: їх 900+, і від «не платив» їх не відрізнити."""
        from app.services.payment_ops import reconcile_pending

        _pending_reg(instance)
        registration.payment_status = 'unpaid'
        db.session.flush()
        mock_liqpay.check_status.return_value = {
            'status': 'wait_accept', 'payment_id': 'PAY-1', 'amount': 1000,
        }

        report = reconcile_pending(service=mock_liqpay)

        assert report['checked'] == 1
        assert registration.payment_status == 'unpaid'

    def test_success_marks_paid_and_confirms(self, mock_liqpay, user, instance):
        from app.services.payment_ops import reconcile_pending

        reg = _pending_reg(instance)
        mock_liqpay.check_status.return_value = {
            'status': 'success', 'payment_id': 'PAY-OK', 'amount': 1000,
        }

        report = reconcile_pending(service=mock_liqpay)

        assert report['updated'] == 1
        assert reg.payment_status == 'paid'
        assert reg.status == 'confirmed'

    def test_still_wait_accept_changes_nothing(self, mock_liqpay, user, instance):
        """Доки верифікація магазину не відновлена, звірка мусить мовчати."""
        from app.services.payment_ops import reconcile_pending

        reg = _pending_reg(instance)
        mock_liqpay.check_status.return_value = {
            'status': 'wait_accept', 'payment_id': 'PAY-W', 'amount': 1000,
        }

        report = reconcile_pending(service=mock_liqpay)

        assert report['unchanged'] == 1
        assert report['updated'] == 0
        assert reg.payment_status == 'pending'

    def test_api_failure_does_not_stop_the_rest(self, mock_liqpay, user, instance):
        """Один недоступний рядок не має ховати решту -- інакше звірка
        мовчки робить менше, ніж звітує."""
        from app.services.payment_ops import reconcile_pending

        first = _pending_reg(instance)
        second = _pending_reg(instance)
        by_order = {
            f'REG-{first.id}': None,
            f'REG-{second.id}': {
                'status': 'success', 'payment_id': 'PAY-2', 'amount': 1000,
            },
        }
        mock_liqpay.check_status.side_effect = lambda order_id: by_order[order_id]

        report = reconcile_pending(service=mock_liqpay)

        assert report['failed'] == 1
        assert report['updated'] == 1
        assert second.payment_status == 'paid'

    def test_exception_on_one_row_does_not_abort_the_run(
            self, mock_liqpay, instance):
        """Мережа до LiqPay падає не лише поверненням None. Виняток на
        одному замовленні не має ховати решту: інакше перший же таймаут
        перетворює звірку на 500 і не робить нічого."""
        from app.services.payment_ops import reconcile_pending

        first = _pending_reg(instance)
        second = _pending_reg(instance)
        # Комітимо навмисно: у проді зависли платежі приїхали з попередніх
        # запитів, тобто давно в базі. Лише flush лишив би їх усередині
        # збереженої точки сесії, і відкат після винятку зніс би саме те,
        # що тест перевіряє, -- обробку РЕШТИ рядків.
        db.session.commit()

        def _flaky(order_id):
            if order_id == f'REG-{first.id}':
                raise ConnectionError('boom')
            return {'status': 'success', 'payment_id': 'PAY-2', 'amount': 1000}

        mock_liqpay.check_status.side_effect = _flaky

        report = reconcile_pending(service=mock_liqpay)

        assert report['failed'] == 1
        assert report['updated'] == 1
        assert second.payment_status == 'paid'

    def test_covers_online_enrollments(self, mock_liqpay, pending_enrollment):
        """Звірка, що мовчки пропускає ONL-, -- пастка на майбутнє."""
        from app.services.payment_ops import reconcile_pending

        mock_liqpay.check_status.return_value = {
            'status': 'success', 'payment_id': 'PAY-ONL', 'amount': 500,
        }

        report = reconcile_pending(service=mock_liqpay)

        assert report['updated'] == 1
        assert pending_enrollment.payment_status == 'paid'

    def test_unconfigured_service_reports_error(self, mock_liqpay, user, instance):
        from app.services.payment_ops import reconcile_pending

        _pending_reg(instance)
        mock_liqpay.is_configured = False

        report = reconcile_pending(service=mock_liqpay)

        assert report['error']
        assert report['checked'] == 0
        mock_liqpay.check_status.assert_not_called()

    def test_max_age_skips_long_dead_rows(self, mock_liqpay, instance):
        """Без вікна фонова джоба довбила б LiqPay ВІЧНО по рядку, який не
        зрушить ніколи: людина взяла рахунок, а `pending` лишився назавжди."""
        from app.services.payment_ops import reconcile_pending

        fresh = _pending_reg(instance)
        stale = _pending_reg(instance)
        stale.created_at = utcnow() - timedelta(days=30)
        db.session.flush()
        mock_liqpay.check_status.return_value = {
            'status': 'wait_accept', 'payment_id': 'PAY-W', 'amount': 1000,
        }

        report = reconcile_pending(service=mock_liqpay, max_age_days=7)

        assert report['checked'] == 1
        mock_liqpay.check_status.assert_called_once_with(f'REG-{fresh.id}')

    def test_without_max_age_takes_everything(self, mock_liqpay, instance):
        """Поведінка кнопки: адмін попросив -- дивимось усе, без вікна."""
        from app.services.payment_ops import reconcile_pending

        stale = _pending_reg(instance)
        stale.created_at = utcnow() - timedelta(days=400)
        db.session.flush()
        mock_liqpay.check_status.return_value = {
            'status': 'wait_accept', 'payment_id': 'PAY-W', 'amount': 1000,
        }

        report = reconcile_pending(service=mock_liqpay)

        assert report['checked'] == 1

    def test_limit_caps_one_run(self, mock_liqpay, user, instance):
        """Запобіжник від майбутнього: прогін не має ставати сотнями
        запитів до чужого API в одному HTTP-запиті адмінки."""
        from app.services.payment_ops import reconcile_pending

        for _ in range(3):
            _pending_reg(instance)
        mock_liqpay.check_status.return_value = {
            'status': 'wait_accept', 'payment_id': 'PAY-W', 'amount': 1000,
        }

        report = reconcile_pending(service=mock_liqpay, limit=2)

        assert report['checked'] == 2
