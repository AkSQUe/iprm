"""Повернення коштів: тарифна сітка політики і часткові повернення.

Головне, що тут стережеться -- різниця між ЧАСТКОВИМ і ПОВНИМ поверненням.
Часткове не має чіпати ані статус замовлення, ані місце, ані доступ:
людина, якій повернули половину за перенесений захід, лишається учасником.
Повне, навпаки, мусить провести всі наслідки. Плутанина між цими двома
випадками коштує або місця учаснику, або грошей організатору.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from tests import refund_fixtures

from app.extensions import db
from app.models.payment_transaction import PaymentTransaction
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import refund_policy
from app.services.payment_ops import PaymentOps, resolve_refund_amount


def _uid():
    return uuid4().hex[:8]


@pytest.fixture(autouse=True)
def clean(app):
    """Прибрати за собою закомічене: сервіс комітить, а БД спільна."""
    yield
    refund_fixtures.purge('refund-', 'refund-', wipe_online=True)


@pytest.fixture
def user(app):
    item = User.create_with_password(
        f'refund-{_uid()}@test.com', 'password123',
        first_name='Ірина', last_name='Мельник',
    )
    db.session.flush()
    return item


@pytest.fixture
def instance(app, user):
    course = Course(
        title='Курс', slug=f'refund-{_uid()}', event_type='course',
        base_price=1000, is_active=True, created_by=user.id,
    )
    db.session.add(course)
    db.session.flush()
    item = CourseInstance(
        course_id=course.id, status='active', event_format='offline',
        price=1000, start_date=utcnow() + timedelta(days=30),
    )
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


@pytest.fixture
def paid_enrollment(app, user):
    course = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Онлайн-курс', slug=f'onl-refund-{_uid()}',
        price=Decimal('4000'), access_url='https://example.test/register/x',
        is_published=True,
    )
    db.session.add(course)
    db.session.flush()
    item = OnlineEnrollment(
        user_id=user.id, online_course_id=course.id,
        payment_amount=Decimal('4000'), payment_status='paid',
        status='active', paid_at=utcnow(),
    )
    db.session.add(item)
    db.session.flush()
    return item


@pytest.fixture
def liqpay():
    service = MagicMock()
    service.validate_callback_signature.return_value = True
    service.is_configured = True
    service.create_refund_request.return_value = {'status': 'reversed'}
    return service


@pytest.fixture
def ops(liqpay):
    return PaymentOps(liqpay)


# --------------------------- тарифна сітка §4.1 ---------------------------

class TestPolicyTiers:

    @pytest.mark.parametrize('days,percent', [
        (30, 100),
        (7.5, 100),
        # Політика каже "БІЛЬШЕ ніж за 7 днів" -- рівно сім днів це вже
        # сходинка 50%, і саме цю межу найлегше зсунути помилково.
        (7, 50),
        (5, 50),
        (3, 50),
        (2.9, 25),
        (0.5, 25),
        (-1, 0),
    ])
    def test_percent_by_days(self, days, percent):
        code = refund_policy.tier_for_days(days)
        assert refund_policy.TIER_PERCENT[code] == percent

    def test_quote_uses_event_start(self, paid_reg, instance):
        instance.start_date = utcnow() + timedelta(days=5)
        quote = refund_policy.quote_registration(paid_reg)
        assert quote.percent == 50
        assert quote.amount == Decimal('500.00')
        assert quote.refundable is True

    def test_started_event_returns_nothing(self, paid_reg, instance):
        instance.start_date = utcnow() - timedelta(hours=1)
        quote = refund_policy.quote_registration(paid_reg)
        assert quote.percent == 0
        assert quote.amount == Decimal('0.00')
        assert 'неявк' in quote.note

    def test_missing_date_suggests_full_but_flags_it(self, paid_reg, instance):
        instance.start_date = None
        quote = refund_policy.quote_registration(paid_reg)
        assert quote.code == 'no_event_date'
        assert quote.amount == Decimal('1000.00')
        assert quote.note

    def test_requested_at_shifts_the_tier(self, paid_reg, instance):
        """Відсоток рахується від дати ЗАЯВКИ, а не від дати натискання."""
        instance.start_date = utcnow() + timedelta(days=2)
        late = refund_policy.quote_registration(paid_reg)
        early = refund_policy.quote_registration(
            paid_reg, requested_at=utcnow() - timedelta(days=10))
        assert late.percent == 25
        assert early.percent == 100

    def test_digital_before_access_is_full(self, paid_enrollment):
        quote = refund_policy.quote_enrollment(paid_enrollment)
        assert quote.percent == 100
        assert quote.refundable is True

    def test_digital_after_access_is_blocked(self, paid_enrollment):
        paid_enrollment.provisioned_at = utcnow()
        quote = refund_policy.quote_enrollment(paid_enrollment)
        assert quote.percent == 0
        assert quote.refundable is False


# ------------------------------ вибір суми ------------------------------

class TestResolveAmount:

    def test_none_means_whole_remainder(self, paid_reg):
        amount, problem = resolve_refund_amount(paid_reg, None)
        assert problem is None
        assert amount == Decimal('1000.00')

    def test_remainder_shrinks_after_partial(self, paid_reg):
        paid_reg.refunded_amount = Decimal('400')
        amount, problem = resolve_refund_amount(paid_reg, None)
        assert amount == Decimal('600.00')

    def test_over_remainder_rejected(self, paid_reg):
        paid_reg.refunded_amount = Decimal('900')
        amount, problem = resolve_refund_amount(paid_reg, '200')
        assert amount is None
        assert 'залишок' in problem

    @pytest.mark.parametrize('bad', ['0', '-5', 'сто', ''])
    def test_bad_amounts(self, paid_reg, bad):
        amount, problem = resolve_refund_amount(paid_reg, bad)
        if bad == '':
            # Порожній рядок -- це «весь залишок», а не помилка.
            assert amount == Decimal('1000.00')
        else:
            assert amount is None and problem

    def test_comma_decimal_accepted(self, paid_reg):
        amount, problem = resolve_refund_amount(paid_reg, '250,50')
        assert problem is None
        assert amount == Decimal('250.50')

    def test_nothing_left_to_refund(self, paid_reg):
        paid_reg.refunded_amount = Decimal('1000')
        amount, problem = resolve_refund_amount(paid_reg, None)
        assert amount is None
        assert 'всю суму' in problem


# --------------------------- часткове повернення ---------------------------

class TestPartialRefund:

    def test_partial_keeps_registration_active(self, ops, paid_reg, user):
        ok, message = ops.initiate_refund(
            paid_reg, user, amount='500', reason='Заявка за 5 днів')

        assert ok, message
        assert paid_reg.refunded_total == Decimal('500.00')
        assert paid_reg.refund_remaining == Decimal('500.00')
        # Найважливіше: замовлення лишається оплаченим і діючим.
        assert paid_reg.payment_status == 'paid'
        assert paid_reg.status == 'confirmed'
        assert paid_reg.refund_reason == 'Заявка за 5 днів'

    def test_partial_is_logged_as_paid_with_amount(self, ops, paid_reg, user):
        ops.initiate_refund(paid_reg, user, amount='500')

        txn = PaymentTransaction.query.filter_by(
            registration_id=paid_reg.id, source='refund').one()
        assert txn.mapped_status == 'paid'
        assert txn.amount == Decimal('500.00')

    def test_second_partial_completes_the_refund(self, ops, paid_reg, user):
        ops.initiate_refund(paid_reg, user, amount='400')
        ok, message = ops.initiate_refund(paid_reg, user, amount='600')

        assert ok, message
        assert paid_reg.refunded_total == Decimal('1000.00')
        assert paid_reg.payment_status == 'refunded'
        assert paid_reg.status == 'cancelled'

    def test_full_refund_without_amount(self, ops, paid_reg, user):
        ok, _ = ops.initiate_refund(paid_reg, user)

        assert ok
        assert paid_reg.payment_status == 'refunded'
        assert paid_reg.refunded_total == Decimal('1000.00')

    def test_over_remainder_never_reaches_liqpay(self, ops, liqpay, paid_reg, user):
        paid_reg.refunded_amount = Decimal('800')
        ok, problem = ops.initiate_refund(paid_reg, user, amount='500')

        assert not ok
        assert 'залишок' in problem
        liqpay.create_refund_request.assert_not_called()

    def test_refunded_order_cannot_be_refunded_again(self, ops, paid_reg, user):
        ops.initiate_refund(paid_reg, user)
        ok, problem = ops.initiate_refund(paid_reg, user, amount='100')

        assert not ok
        assert 'оплачених' in problem


# ------------------------------- запобіжники -------------------------------

class TestRefundGuards:

    def test_reversed_echo_does_not_swallow_partial(self, ops, paid_reg, user):
        """Луна LiqPay після часткового повернення не скасовує реєстрацію.

        LiqPay повідомляє про повернення статусом `reversed` -- тим самим,
        яким позначає повне. Без запобіжника цей сигнал перевів би
        замовлення у 'refunded' цілком, і людина втратила б місце на
        заході, за яке половина грошей у нас лишилась.
        """
        ops.initiate_refund(paid_reg, user, amount='500')

        ok, message = ops.update_payment_status(
            paid_reg, 'refunded', source='callback', liqpay_status='reversed')

        assert ok
        assert message == 'partial refund already recorded'
        assert paid_reg.payment_status == 'paid'
        assert paid_reg.status == 'confirmed'

    def test_external_full_refund_fills_the_amount(self, ops, paid_reg):
        """Повернення повз систему (у кабінеті LiqPay) приймаємо як повне."""
        ok, _ = ops.update_payment_status(
            paid_reg, 'refunded', source='callback', liqpay_status='reversed')

        assert ok
        assert paid_reg.payment_status == 'refunded'
        assert paid_reg.refunded_total == Decimal('1000.00')
        assert paid_reg.refunded_at is not None

    def test_liqpay_rejection_changes_nothing(self, ops, liqpay, paid_reg, user):
        # Комітимо до виклику: відмова робить rollback, і без коміту разом
        # з нею зникла б і сама реєстрація, тож перевіряти було б нічого.
        db.session.commit()
        liqpay.create_refund_request.return_value = {
            'status': 'error', 'err_description': 'payment_not_found'}

        ok, problem = ops.initiate_refund(paid_reg, user, amount='500')

        assert not ok
        assert 'payment_not_found' in problem
        db.session.refresh(paid_reg)
        assert paid_reg.refunded_total == Decimal('0')
        assert paid_reg.payment_status == 'paid'

    def test_liqpay_unreachable_changes_nothing(self, ops, liqpay, paid_reg, user):
        db.session.commit()
        liqpay.create_refund_request.return_value = None

        ok, _ = ops.initiate_refund(paid_reg, user, amount='500')

        assert not ok
        db.session.refresh(paid_reg)
        assert paid_reg.refunded_total == Decimal('0')

    def test_provisioned_course_refuses_without_force(
            self, ops, liqpay, paid_enrollment, user):
        paid_enrollment.provisioned_at = utcnow()

        ok, problem = ops.initiate_enrollment_refund(paid_enrollment, user)

        assert not ok
        assert '5.1' in problem
        liqpay.create_refund_request.assert_not_called()

    def test_provisioned_course_refunds_with_force(
            self, ops, paid_enrollment, user):
        paid_enrollment.provisioned_at = utcnow()

        ok, message = ops.initiate_enrollment_refund(
            paid_enrollment, user, force=True, reason='Рішення керівництва')

        assert ok, message
        assert paid_enrollment.payment_status == 'refunded'
        assert paid_enrollment.status == 'cancelled'

    def test_partial_course_refund_keeps_access(self, ops, paid_enrollment, user):
        ok, message = ops.initiate_enrollment_refund(
            paid_enrollment, user, amount='1000')

        assert ok, message
        assert paid_enrollment.payment_status == 'paid'
        assert paid_enrollment.status == 'active'
        assert paid_enrollment.refund_remaining == Decimal('3000.00')


# ------------------------------- звітність -------------------------------

class TestPaymentStats:
    """Часткове повернення лишає замовлення 'paid' -- звіт має це врахувати.

    Перевіряємо ЗМІНУ показників, а не абсолютні числа: таблиця спільна на
    всю тестову сесію, і фіксовані очікування ламались би від сусідніх
    наборів.
    """

    def test_partial_refund_reduces_revenue(self, ops, paid_reg, user):
        before = EventRegistration.payment_stats()

        ops.initiate_refund(paid_reg, user, amount='400')
        after = EventRegistration.payment_stats()

        assert (Decimal(str(before.total_amount))
                - Decimal(str(after.total_amount))) == Decimal('400.00')

    def test_partial_refund_shows_up_in_refunded_sum(self, ops, paid_reg, user):
        before = EventRegistration.payment_stats()

        ops.initiate_refund(paid_reg, user, amount='400')
        after = EventRegistration.payment_stats()

        assert (Decimal(str(after.refunded_amount))
                - Decimal(str(before.refunded_amount))) == Decimal('400.00')
        # Замовлення НЕ переїхало в лічильник повністю повернених.
        assert after.refunded == before.refunded

    def test_full_refund_moves_the_counter(self, ops, paid_reg, user):
        before = EventRegistration.payment_stats()

        ops.initiate_refund(paid_reg, user)
        after = EventRegistration.payment_stats()

        assert after.refunded == before.refunded + 1
        assert (Decimal(str(before.total_amount))
                - Decimal(str(after.total_amount))) == Decimal('1000.00')


# --------------------------------- лист ---------------------------------

class TestRefundEmail:
    """Лист рендериться з реальними числами, а не лише проходить smoke.

    Загальний `test_all_email_templates_render` малює всі шаблони з
    заглушками замість змінних -- він упіймає зламаний синтаксис, але не
    те, що в листі про часткове повернення не видно утриманої суми.
    """

    @staticmethod
    def _render(app, **overrides):
        from flask import render_template

        context = dict(
            user=type('U', (), {'first_name': 'Ірина'})(),
            title='Плазмотерапія',
            order_id='REG-42',
            amount=Decimal('500.00'),
            total=Decimal('1000.00'),
            withheld=Decimal('500.00'),
            is_full=False,
            reason='Заявка за 5 днів до заходу',
            refund_policy_url='https://example.test/refund',
        )
        context.update(overrides)
        with app.test_request_context('/'):
            return render_template('emails/refund_processed.html', **context)

    def test_partial_shows_withheld_amount(self, app):
        html = self._render(app)

        assert '500.00' in html
        assert '1000.00' in html
        assert 'Утримано' in html
        assert 'Заявка за 5 днів до заходу' in html

    def test_full_refund_hides_withheld_row(self, app):
        html = self._render(app, amount=Decimal('1000.00'),
                            withheld=Decimal('0.00'), is_full=True)

        assert 'Утримано' not in html
        assert 'повну суму' in html

    def test_missing_reason_does_not_leave_empty_block(self, app):
        html = self._render(app, reason=None)

        assert 'Підстава' not in html


# ---------------------------- знайдене рецензією ----------------------------

class TestAmountParsingHardening:
    """`Decimal` приймає більше, ніж здається на перший погляд.

    "nan" -- валідний Decimal, і саме на ньому падала сторінка: порівняння
    `Decimal("NaN") <= 0` не повертає False, а піднімає InvalidOperation --
    причому вже поза try-блоком розбору.
    """

    @pytest.mark.parametrize('raw', ['nan', 'NaN', 'sNaN', 'Infinity',
                                     '-Infinity', 'inf'])
    def test_non_finite_is_refused_not_crashing(self, paid_reg, raw):
        amount, problem = resolve_refund_amount(paid_reg, raw)

        assert amount is None
        assert problem

    def test_scientific_notation_still_works(self, paid_reg):
        amount, problem = resolve_refund_amount(paid_reg, '1e2')
        assert problem is None
        assert amount == Decimal('100.00')

    def test_sub_kopiyka_rounds_to_zero_and_is_refused(self, paid_reg):
        amount, problem = resolve_refund_amount(paid_reg, '0.001')
        assert amount is None
        assert 'більшою за нуль' in problem


class TestRescueWhenDatabaseFails:
    """Гроші пішли, а транзакція впала -- слід має лишитись.

    Без цього rollback стирає `refunded_amount`, адмін бачить «помилка»,
    тисне ще раз, і LiqPay проводить ДРУГЕ часткове повернення на ту саму
    суму: підстав відхилити його в нього немає.
    """

    def test_amount_survives_a_failed_status_update(
            self, ops, paid_reg, user, monkeypatch):
        db.session.commit()
        # Повернення повне, тож спрацює гілка finalize(); ламаємо саме її.
        monkeypatch.setattr(
            PaymentOps, 'update_payment_status',
            lambda self, *a, **k: (False, 'db error'))

        ok, message = ops.initiate_refund(paid_reg, user)

        # Помилка -- свідомо: стан потребує людини.
        assert not ok
        assert 'НЕ повторюйте' in message
        db.session.refresh(paid_reg)
        # Але сума збережена, тож повторне повернення вже не пройде.
        assert paid_reg.refunded_total == Decimal('1000.00')

    def test_second_attempt_is_refused_after_rescue(
            self, ops, paid_reg, user, monkeypatch):
        db.session.commit()
        monkeypatch.setattr(
            PaymentOps, 'update_payment_status',
            lambda self, *a, **k: (False, 'db error'))
        ops.initiate_refund(paid_reg, user)
        monkeypatch.undo()

        ok, problem = ops.initiate_refund(paid_reg, user)

        assert not ok
        assert 'всю суму' in problem

    def test_rescue_leaves_a_journal_row(self, ops, paid_reg, user, monkeypatch):
        db.session.commit()
        monkeypatch.setattr(
            PaymentOps, 'update_payment_status',
            lambda self, *a, **k: (False, 'db error'))

        ops.initiate_refund(paid_reg, user)

        txn = PaymentTransaction.query.filter_by(
            registration_id=paid_reg.id, source='refund').one()
        assert txn.amount == Decimal('1000.00')


class TestRepeatRefundEmail:
    """Друга операція за тим самим замовленням не має брехати про утримання."""

    @staticmethod
    def _context(order, amount):
        """Те, що потрапляє в шаблон листа."""
        total = Decimal(str(order.payment_amount or 0))
        refunded_total = Decimal(str(order.refunded_amount or 0))
        return {
            'amount': amount,
            'refunded_total': refunded_total,
            'is_repeat': refunded_total > amount,
            'withheld': max(Decimal('0'), total - refunded_total),
            'is_full': refunded_total >= total > 0,
        }

    def test_first_partial_reports_what_is_withheld(self, ops, paid_reg, user):
        ops.initiate_refund(paid_reg, user, amount='400')

        ctx = self._context(paid_reg, Decimal('400'))

        assert ctx['is_full'] is False
        assert ctx['is_repeat'] is False
        assert ctx['withheld'] == Decimal('600')

    def test_second_partial_reports_the_order_as_fully_refunded(
            self, ops, paid_reg, user):
        ops.initiate_refund(paid_reg, user, amount='400')
        ops.initiate_refund(paid_reg, user, amount='600')

        ctx = self._context(paid_reg, Decimal('600'))

        # Саме тут стара формула казала "утримано 400" за повністю
        # поверненим замовленням.
        assert ctx['is_full'] is True
        assert ctx['is_repeat'] is True
        assert ctx['withheld'] == Decimal('0')
        assert ctx['refunded_total'] == Decimal('1000')


class TestDiscountIsNotSubtractedTwice:
    """Повернення рахується від СПЛАЧЕНОГО, і знижка вже в ньому.

    `promo_service` виставляє payment_amount як (прайс - знижка), тож усе
    нижче по контуру працює з чистою сумою. Спокуса відняти знижку ще раз
    виникає щоразу, коли хтось бачить у черзі "100%" поруч із дорожчим
    прайсом -- і коштувала б людям частини їхніх грошей.
    """

    def test_quote_is_based_on_paid_amount(self, paid_reg, instance):
        """Прайс 6000, промокод -1200, сплачено 4800 -> повертаємо 4800."""
        paid_reg.payment_amount = Decimal('4800')
        paid_reg.discount_amount = Decimal('1200')
        db.session.flush()

        quote = refund_policy.quote_registration(paid_reg)

        assert quote.percent == 100
        assert quote.amount == Decimal('4800.00')

    def test_remaining_ignores_the_discount(self, paid_reg):
        paid_reg.payment_amount = Decimal('4800')
        paid_reg.discount_amount = Decimal('1200')
        db.session.flush()

        assert paid_reg.refund_remaining == Decimal('4800')

    def test_refund_returns_what_was_paid(self, ops, paid_reg, user):
        paid_reg.payment_amount = Decimal('4800')
        paid_reg.discount_amount = Decimal('1200')
        db.session.flush()

        ok, message = ops.initiate_refund(paid_reg, user)

        assert ok, message
        assert paid_reg.refunded_total == Decimal('4800.00')

    def test_price_before_discount_is_available_for_display(self, paid_reg):
        """Прайс потрібен лише щоб пояснити цифру адміну, не для розрахунку."""
        paid_reg.payment_amount = Decimal('4800')
        paid_reg.discount_amount = Decimal('1200')

        assert paid_reg.has_discount is True
        assert paid_reg.amount_before_discount == Decimal('6000')

    def test_order_without_discount_reports_none(self, paid_reg):
        assert paid_reg.has_discount is False
        assert paid_reg.amount_before_discount == paid_reg.payment_amount

