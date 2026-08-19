"""Заявки на повернення: правила подання й фіксація дати.

Найважливіше тут -- §4.2: відсоток рахується від дати ПОДАННЯ заявки. Саме
заради цього заявка й існує як окрема сутність, тож тест на застиглу
сходинку -- головний у файлі.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from tests import refund_fixtures

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import refund_requests
from app.services.payment_ops import PaymentOps


def _uid():
    return uuid4().hex[:8]


@pytest.fixture(autouse=True)
def clean(app):
    """Прибрати за собою закомічене: сервіс комітить, а БД спільна."""
    yield
    refund_fixtures.purge('rreq-', 'rreq-', wipe_online=True)


@pytest.fixture
def user(app):
    item = User.create_with_password(
        f'rreq-{_uid()}@test.com', 'password123',
        first_name='Оксана', last_name='Гриценко',
    )
    db.session.flush()
    return item


@pytest.fixture
def instance(app, user):
    course = Course(title='Курс', slug=f'rreq-{_uid()}', is_active=False,
                    created_by=user.id)
    db.session.add(course)
    db.session.flush()
    item = CourseInstance(course_id=course.id, status='published', price=1000,
                          start_date=utcnow() + timedelta(days=30))
    db.session.add(item)
    db.session.flush()
    return item


@pytest.fixture
def paid_reg(app, user, instance):
    item = EventRegistration(
        user_id=user.id, instance_id=instance.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status='confirmed', payment_status='paid',
        payment_amount=Decimal('1000'), paid_at=utcnow(),
    )
    db.session.add(item)
    db.session.flush()
    return item


@pytest.fixture(autouse=True)
def quiet_mail(monkeypatch):
    """Листи тут не предмет перевірки, а їх три на кожну заявку."""
    from app.services.email_service import EmailService
    for name in ('send_refund_request_received',
                 'send_refund_request_notification',
                 'send_refund_request_declined'):
        monkeypatch.setattr(EmailService, name, staticmethod(lambda *a, **k: None))


class TestEligibility:

    def test_paid_order_can_be_requested(self, paid_reg):
        assert refund_requests.can_request(paid_reg) == (True, None)

    def test_unpaid_order_cannot(self, paid_reg):
        paid_reg.payment_status = 'unpaid'
        ok, problem = refund_requests.can_request(paid_reg)
        assert not ok and 'оплаченим' in problem

    def test_fully_refunded_order_cannot(self, paid_reg):
        paid_reg.refunded_amount = Decimal('1000')
        ok, problem = refund_requests.can_request(paid_reg)
        assert not ok and 'всю суму' in problem

    def test_second_open_request_is_blocked(self, paid_reg, user):
        refund_requests.create(paid_reg, user, reason='Перша')

        ok, problem = refund_requests.can_request(paid_reg)

        assert not ok and 'на розгляді' in problem

    def test_partially_refunded_order_can_still_be_requested(self, paid_reg):
        """Повернули половину -- за рештою можна звертатись повторно."""
        paid_reg.refunded_amount = Decimal('400')
        assert refund_requests.can_request(paid_reg) == (True, None)


class TestCreate:

    def test_reason_is_required(self, paid_reg, user):
        item, problem = refund_requests.create(paid_reg, user, reason='   ')

        assert item is None
        assert 'причину' in problem

    def test_snapshot_of_policy_is_stored(self, paid_reg, user, instance):
        instance.start_date = utcnow() + timedelta(days=5)
        db.session.flush()

        item, _ = refund_requests.create(paid_reg, user, reason='Не встигаю')

        assert item.quoted_percent == 50
        assert item.quoted_amount == Decimal('500.00')
        assert item.quoted_code == 'standard'

    def test_request_links_to_the_right_order(self, paid_reg, user):
        item, _ = refund_requests.create(paid_reg, user, reason='Причина')

        assert item.registration_id == paid_reg.id
        assert item.enrollment_id is None
        assert item.order_code == f'REG-{paid_reg.id}'
        assert item.kind == 'registration'

    def test_payout_details_are_optional(self, paid_reg, user):
        item, _ = refund_requests.create(paid_reg, user, reason='Причина',
                                         payout_details='  ')
        assert item.payout_details is None


class TestPolicyIsFrozenAtSubmission:
    """§4.2: дата подання визначає відсоток -- і потім не рухається.

    Це головна причина, чому заявка існує окремою сутністю. Доти адмін
    відкривав сторінку повернення й отримував сходинку на момент кліку:
    звернення, що пролежало у пошті три дні, коштувало учаснику половини.
    """

    def test_moving_the_event_does_not_shrink_the_quote(
            self, paid_reg, user, instance):
        item, _ = refund_requests.create(paid_reg, user, reason='Причина')
        assert item.quoted_percent == 100

        # Захід наблизився (або заявка пролежала в черзі) -- жива політика
        # вже дала б 25%.
        instance.start_date = utcnow() + timedelta(days=1)
        db.session.flush()

        from app.services import refund_policy
        assert refund_policy.quote_registration(paid_reg).percent == 25
        # А знімок заявки лишився тим, який учасник бачив при поданні.
        assert item.quoted_percent == 100
        assert item.quoted_amount == Decimal('1000.00')


class TestDecisions:

    def test_reject_records_note_and_closes(self, paid_reg, user):
        item, _ = refund_requests.create(paid_reg, user, reason='Причина')

        ok, message = refund_requests.reject(item, user, 'Захід уже відбувся')

        assert ok, message
        assert item.status == 'rejected'
        assert item.decision_note == 'Захід уже відбувся'
        assert item.decided_at is not None
        assert item.decided_by_id == user.id

    def test_rejected_request_cannot_be_rejected_twice(self, paid_reg, user):
        item, _ = refund_requests.create(paid_reg, user, reason='Причина')
        refund_requests.reject(item, user, 'Перше рішення')

        ok, problem = refund_requests.reject(item, user, 'Друге рішення')

        assert not ok and 'вже розглянуто' in problem

    def test_rejecting_frees_the_order_for_a_new_request(self, paid_reg, user):
        """Відмова -- не вирок: обставини можуть змінитись."""
        item, _ = refund_requests.create(paid_reg, user, reason='Перша')
        refund_requests.reject(item, user, 'Недостатньо підстав')

        assert refund_requests.can_request(paid_reg) == (True, None)

    def test_mark_approved_closes_without_email(self, paid_reg, user):
        item, _ = refund_requests.create(paid_reg, user, reason='Причина')

        refund_requests.mark_approved(item, user)
        db.session.commit()

        assert item.status == 'approved'
        assert item.decided_by_id == user.id

    def test_pending_count_sees_only_open(self, paid_reg, user):
        before = refund_requests.pending_count()
        item, _ = refund_requests.create(paid_reg, user, reason='Причина')
        assert refund_requests.pending_count() == before + 1

        refund_requests.reject(item, user, 'Ні')
        assert refund_requests.pending_count() == before


class TestMoneyStaysInPaymentOps:
    """Заявка не рухає гроші -- це робота payment_ops."""

    def test_creating_a_request_does_not_touch_the_order(self, paid_reg, user):
        refund_requests.create(paid_reg, user, reason='Причина')

        assert paid_reg.payment_status == 'paid'
        assert paid_reg.refunded_total == Decimal('0')
        assert paid_reg.status == 'confirmed'

    def test_refund_still_goes_through_payment_ops(self, paid_reg, user):
        refund_requests.create(paid_reg, user, reason='Причина')

        liqpay = MagicMock()
        liqpay.create_refund_request.return_value = {'status': 'reversed'}
        ok, _ = PaymentOps(liqpay).initiate_refund(paid_reg, user, amount='300')

        assert ok
        assert paid_reg.refunded_total == Decimal('300.00')
