"""Оплата онлайн-курсів: перехід статусів і видача доступу.

Найважливіше тут -- порядок: спершу фіксується оплата, потім видається
доступ. Якщо переставити, збій видачі відкотив би оплату, і система
вважала б неоплаченим замовлення, за яке гроші вже прийшли.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.payment_transaction import PaymentTransaction
from app.models.user import User
from app.services import sintegrum_access
from app.services.payment_ops import PaymentOps, parse_order_id

ACCESS_URL = 'https://multimededu.sintegrum.com/register/abc'


@pytest.fixture(autouse=True)
def clean(app):
    """Більшість тестів тут працює на flush і відкочується сама.

    Але `test_retry_job_recovers_stuck_order` комітить -- інакше джоба не
    побачила б замовлення, -- і закомічені рядки переживають тестову
    транзакцію. Далі вони валили сусідні набори, які чистять каталог:
    курс під замовленням не видаляється (FK RESTRICT).
    """
    yield
    OnlineEnrollment.query.delete()
    OnlineCourse.query.delete()
    db.session.commit()


@pytest.fixture
def user(app):
    item = User.create_with_password(
        f'onl-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Ольга', last_name='Коваль',
    )
    db.session.flush()
    return item


@pytest.fixture
def course(app):
    item = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Плазмотерапія',
        slug=f'oe-{uuid4().hex[:8]}',
        price=Decimal('4500'),
        access_url=ACCESS_URL,
        is_published=True,
    )
    db.session.add(item)
    db.session.flush()
    return item


@pytest.fixture
def enrollment(app, user, course):
    item = OnlineEnrollment(
        user_id=user.id, online_course_id=course.id,
        payment_amount=Decimal('4500'), payment_status='unpaid',
        status='pending',
    )
    db.session.add(item)
    db.session.flush()
    return item


@pytest.fixture
def ops():
    service = MagicMock()
    service.validate_callback_signature.return_value = True
    service.is_configured = True
    return PaymentOps(service)


# ----------------------------- розбір order_id -----------------------------

@pytest.mark.parametrize('order_id,expected', [
    ('REG-42', ('registration', 42)),
    ('ONL-7', ('enrollment', 7)),
    ('REG-abc', ('registration', None)),
    ('ONL-', ('enrollment', None)),
    ('XXX-1', (None, None)),
    ('', (None, None)),
])
def test_parse_order_id(order_id, expected):
    assert parse_order_id(order_id) == expected


def test_order_id_property(enrollment):
    assert enrollment.order_id == f'ONL-{enrollment.id}'


# ----------------------------- переходи статусів -----------------------------

def test_unpaid_to_paid_grants_access(ops, enrollment):
    ok, _msg = ops.update_enrollment_status(
        enrollment, 'paid', 'pay-1', amount=4500,
    )
    assert ok is True
    assert enrollment.payment_status == 'paid'
    assert enrollment.status == 'active'
    assert enrollment.paid_at is not None
    assert enrollment.access_token
    assert enrollment.provisioned_at is not None
    assert enrollment.access_issued_count == 1


def test_amount_mismatch_rejected(ops, enrollment):
    ok, msg = ops.update_enrollment_status(
        enrollment, 'paid', 'pay-1', amount=100,
    )
    assert ok is False
    assert msg == 'amount mismatch'
    assert enrollment.payment_status != 'paid'


def test_invalid_transition_is_noop(ops, enrollment):
    enrollment.payment_status = 'refunded'
    db.session.flush()

    ok, msg = ops.update_enrollment_status(enrollment, 'paid', amount=4500)
    assert ok is True
    assert msg == 'no-op transition'


def test_refund_revokes_access(ops, enrollment):
    ops.update_enrollment_status(enrollment, 'paid', 'pay-1', amount=4500)
    assert enrollment.access_token

    ops.update_enrollment_status(enrollment, 'refunded', 'pay-1')

    assert enrollment.payment_status == 'refunded'
    assert enrollment.status == 'cancelled'
    # Гроші повернули -- посилання на курс має перестати працювати.
    assert enrollment.access_token is None


# ----------------------------- callback -----------------------------

def _callback(ops, order_id, status='success', amount=4500, payment_id='pay-1'):
    ops.liqpay.decode_callback.return_value = {
        'order_id': order_id, 'status': status,
        'payment_id': payment_id, 'amount': amount,
    }
    return ops.process_callback('data', 'sig')


def test_callback_pays_enrollment(ops, enrollment):
    ok, _msg = _callback(ops, enrollment.order_id)
    db.session.refresh(enrollment)

    assert ok is True
    assert enrollment.payment_status == 'paid'


def test_callback_rejects_bad_signature(ops, enrollment):
    ops.liqpay.validate_callback_signature.return_value = False
    ok, msg = _callback(ops, enrollment.order_id)

    assert ok is False
    assert msg == 'invalid signature'


def test_callback_with_unknown_enrollment(ops, enrollment):
    ok, msg = _callback(ops, 'ONL-99999999')
    assert ok is False
    assert msg == 'enrollment not found'


def test_callback_is_idempotent(ops, enrollment):
    _callback(ops, enrollment.order_id)
    ok, msg = _callback(ops, enrollment.order_id)

    assert ok is True
    assert msg == 'already processed'


def test_callback_rejects_wrong_amount(ops, enrollment):
    ok, msg = _callback(ops, enrollment.order_id, amount=1)
    assert ok is False
    assert msg == 'amount mismatch'


def test_unknown_prefix_still_rejected(ops, enrollment):
    ok, msg = _callback(ops, 'XXX-1')
    assert ok is False
    assert msg == 'unknown order_id'


# ----------------------------- журнал транзакцій -----------------------------

def test_transaction_is_logged_against_enrollment(ops, enrollment):
    ops.update_enrollment_status(enrollment, 'paid', 'pay-1', amount=4500)

    txn = PaymentTransaction.query.filter_by(enrollment_id=enrollment.id).first()
    assert txn is not None
    assert txn.registration_id is None
    assert txn.order_id == enrollment.order_id
    assert txn.mapped_status == 'paid'


# ----------------------------- порядок оплата -> доступ -----------------------------

def test_payment_survives_failed_provisioning(ops, enrollment, monkeypatch):
    """Збій видачі доступу НЕ відкочує оплату.

    Гроші вже списані. Замовлення лишається оплаченим без доступу -- це
    видимий стан, який підбирає джоба, а не мовчазна втрата платежу.
    """
    def _boom(*args, **kwargs):
        raise RuntimeError('provider down')

    monkeypatch.setattr(sintegrum_access, 'provision', _boom)

    ok, _msg = ops.update_enrollment_status(
        enrollment, 'paid', 'pay-1', amount=4500,
    )
    db.session.refresh(enrollment)

    assert ok is True
    assert enrollment.payment_status == 'paid'
    assert enrollment.provisioned_at is None
    assert enrollment.access_token is None


def test_course_without_access_url_leaves_enrollment_unprovisioned(ops, enrollment):
    enrollment.course.access_url = None
    db.session.flush()

    ok, _msg = ops.update_enrollment_status(
        enrollment, 'paid', 'pay-1', amount=4500,
    )
    db.session.refresh(enrollment)

    assert ok is True
    assert enrollment.payment_status == 'paid'
    assert enrollment.provisioned_at is None
    assert enrollment.provision_error


def test_pending_provisioning_finds_stuck_orders(app, enrollment):
    from datetime import timedelta
    from app.models.mixins import utcnow

    enrollment.payment_status = 'paid'
    enrollment.provisioned_at = None
    enrollment.created_at = utcnow() - timedelta(hours=1)
    db.session.flush()

    stuck = sintegrum_access.pending_provisioning()
    assert enrollment.id in [item.id for item in stuck]


# ----------------------------- видача доступу -----------------------------

def test_provision_refuses_unpaid(enrollment):
    with pytest.raises(sintegrum_access.AccessProvisionError):
        sintegrum_access.provision(enrollment)


def test_provision_does_not_call_sintegrum_api(enrollment, monkeypatch):
    """Чинний сценарій (Q1) не звертається до API -- отже його падіння
    не може завадити видачі доступу."""
    import app.services.sintegrum_client as sc

    def _forbidden(*args, **kwargs):
        raise AssertionError('API Sintegrum не має викликатись при видачі доступу')

    monkeypatch.setattr(sc.requests, 'request', _forbidden)

    enrollment.payment_status = 'paid'
    db.session.flush()
    token = sintegrum_access.provision(enrollment)
    assert token


def test_reissue_invalidates_previous_token(enrollment):
    enrollment.payment_status = 'paid'
    db.session.flush()

    first = sintegrum_access.provision(enrollment)
    second = sintegrum_access.reissue(enrollment)

    assert first != second
    assert enrollment.access_token == second
    assert enrollment.access_issued_count == 2


def test_ttl_prefers_course_value(app, course, enrollment):
    from app.models.site_settings import SiteSettings

    settings = SiteSettings.get()
    settings.sintegrum_access_ttl_hours = 72
    course.access_ttl_hours = 5
    db.session.flush()

    assert sintegrum_access.ttl_hours_for(course, settings) == 5
    course.access_ttl_hours = None
    assert sintegrum_access.ttl_hours_for(course, settings) == 72


# ----------------------------- цілісність журналу -----------------------------

def test_transaction_requires_exactly_one_owner(app, enrollment):
    """Рядок без власника не знайде жодна звірка; рядок з обома порахують двічі."""
    import sqlalchemy.exc

    for kwargs in (
        {},  # жодного власника
        {'registration_id': 1, 'enrollment_id': enrollment.id},  # обидва
    ):
        txn = PaymentTransaction(
            order_id='ONL-1', mapped_status='paid', source='manual', **kwargs,
        )
        db.session.add(txn)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db.session.flush()
        db.session.rollback()


# ----------------------------- лист і джоба -----------------------------

def test_access_email_is_queued_on_payment(ops, enrollment, monkeypatch):
    sent = {}

    def _capture(item, url, promo=None):
        sent['order_id'] = item.order_id
        sent['url'] = url
        sent['promo'] = promo
        return None

    from app.services.email_service import EmailService
    monkeypatch.setattr(EmailService, 'send_online_access', staticmethod(_capture))

    ops.update_enrollment_status(enrollment, 'paid', 'pay-1', amount=4500)

    assert sent['order_id'] == enrollment.order_id
    # У листі -- НАШЕ посилання, а не адреса Sintegrum.
    assert enrollment.access_token in sent['url']
    assert ACCESS_URL not in sent['url']


def test_failed_email_does_not_take_away_access(ops, enrollment, monkeypatch):
    """Пошта відвалилась -- доступ усе одно виданий і лежить у кабінеті."""
    from app.services.email_service import EmailService

    def _boom(*args, **kwargs):
        raise RuntimeError('smtp down')

    monkeypatch.setattr(EmailService, 'send_online_access', staticmethod(_boom))

    ok, _msg = ops.update_enrollment_status(
        enrollment, 'paid', 'pay-1', amount=4500,
    )
    db.session.refresh(enrollment)

    assert ok is True
    assert enrollment.access_token
    assert enrollment.provisioned_at is not None


def test_retry_job_recovers_stuck_order(app, enrollment, monkeypatch):
    from datetime import timedelta
    from app.models.mixins import utcnow
    from app.services.email_service import EmailService
    from app.services import scheduler_service

    monkeypatch.setattr(EmailService, 'send_online_access',
                        staticmethod(lambda *a, **k: None))

    enrollment.payment_status = 'paid'
    enrollment.provisioned_at = None
    enrollment.created_at = utcnow() - timedelta(hours=1)
    db.session.commit()

    # Джоба ходить через app_context і лок; тут перевіряємо саме тіло.
    for item in sintegrum_access.pending_provisioning():
        sintegrum_access.provision_and_notify(item)

    db.session.refresh(enrollment)
    assert enrollment.provisioned_at is not None
    assert enrollment.access_token
    assert hasattr(scheduler_service, 'retry_online_access_provisioning')


# ----------------------------- автоматична видача через API -----------------------------

class TestStudentApiProvider:
    """Доступ відкривається так само, як робили руками: студент + курс.

    Живих запитів у Sintegrum тут немає й бути не може -- клієнт підмінено.
    Ці тести і є перевіркою послідовності викликів замість неї.
    """

    @staticmethod
    def _client(**overrides):
        from app.services.sintegrum_client import SintegrumResult

        calls = []
        assigned = []

        class _Client:
            def find_student_by_email(self, email):
                calls.append(('find', email))
                return overrides.get(
                    'find', SintegrumResult(ok=True, data=None))

            def create_student(self, **kwargs):
                calls.append(('create', kwargs.get('email')))
                return overrides.get(
                    'create', SintegrumResult(ok=True, data={'id': 777}))

            def assign_course(self, student_id, course_id):
                calls.append(('assign', student_id, course_id))
                result = overrides.get('assign', SintegrumResult(ok=True, data={}))
                if result.ok:
                    assigned.append(course_id)
                return result

            def assigned_positions(self, user_id):
                calls.append(('progress', user_id))
                # За замовчуванням партнер підтверджує те, що ми щойно
                # призначили: тести, написані до появи звірки, перевіряють
                # не її. Розбіжність задається через overrides.
                return overrides.get('progress', SintegrumResult(
                    ok=True,
                    data=[{'user_id': user_id, 'position_id': cid}
                          for cid in assigned]))

            def revoke_course(self, student_id, course_id):
                calls.append(('revoke', student_id, course_id))
                return SintegrumResult(ok=True, data={})

        return _Client(), calls

    def _provider(self, app, **overrides):
        from app.models.site_settings import SiteSettings

        settings = SiteSettings.get()
        settings.sintegrum_company_alias = 'multimededu'
        db.session.flush()

        client, calls = self._client(**overrides)
        return sintegrum_access.StudentApiProvider(
            client=client, settings=settings), calls

    def test_new_student_is_created_then_course_assigned(self, app, enrollment):
        enrollment.course.access_url = None
        db.session.flush()
        provider, calls = self._provider(app)

        result = provider.provision(enrollment)

        assert [c[0] for c in calls] == ['find', 'create', 'assign', 'progress']
        assert ('assign', 777, enrollment.course.sintegrum_id) in calls
        assert result.student_id == 777
        assert result.target_url == 'https://multimededu.sintegrum.com'

    def test_existing_student_is_reused(self, app, enrollment):
        """Друга покупка не має заводити другий кабінет на той самий email."""
        from app.services.sintegrum_client import SintegrumResult

        provider, calls = self._provider(
            app, find=SintegrumResult(ok=True, data={'id': 42}))

        result = provider.provision(enrollment)

        assert 'create' not in [c[0] for c in calls]
        assert result.student_id == 42

    def test_known_student_id_skips_the_lookup(self, app, enrollment):
        enrollment.sintegrum_student_id = 99
        db.session.flush()
        provider, calls = self._provider(app)

        provider.provision(enrollment)

        assert [c[0] for c in calls] == ['assign', 'progress']

    def test_failed_assignment_raises(self, app, enrollment):
        from app.services.sintegrum_client import SintegrumResult

        provider, _calls = self._provider(
            app, assign=SintegrumResult(ok=False, error='Sintegrum 403'))

        with pytest.raises(sintegrum_access.AccessProvisionError):
            provider.provision(enrollment)

    def test_failed_creation_raises(self, app, enrollment):
        from app.services.sintegrum_client import SintegrumResult

        provider, _calls = self._provider(
            app, create=SintegrumResult(ok=False, error='Sintegrum 422'))

        with pytest.raises(sintegrum_access.AccessProvisionError):
            provider.provision(enrollment)

    def test_provider_choice_prefers_explicit_link(self, app, course):
        """Вписане адміном посилання перемагає: він зробив це свідомо."""
        course.access_url = 'https://multimededu.sintegrum.com/register/abc'
        db.session.flush()
        assert isinstance(sintegrum_access.get_provider(course),
                          sintegrum_access.RegistrationLinkProvider)

        course.access_url = None
        db.session.flush()
        assert isinstance(sintegrum_access.get_provider(course),
                          sintegrum_access.StudentApiProvider)

    def test_student_id_is_remembered_after_provisioning(self, app, enrollment,
                                                         monkeypatch):
        enrollment.course.access_url = None
        enrollment.payment_status = 'paid'
        db.session.flush()
        provider, _calls = self._provider(app)
        monkeypatch.setattr(sintegrum_access, 'get_provider',
                            lambda *a, **k: provider)

        sintegrum_access.provision(enrollment)

        assert enrollment.sintegrum_student_id == 777


class TestEffectivePrice:
    """Ціна береться з Sintegrum; наша -- лише перевизначення."""

    def test_remote_price_is_used_by_default(self, course):
        course.price = None
        course.remote_price = Decimal('3500')
        assert course.effective_price == Decimal('3500')
        assert course.price_is_overridden is False

    def test_our_price_wins_when_set(self, course):
        course.price = Decimal('6000')
        course.remote_price = Decimal('3500')
        assert course.effective_price == Decimal('6000')
        assert course.price_is_overridden is True

    def test_publication_needs_only_a_price(self, course):
        """Посилання більше не потрібне: доступ відкривається через API."""
        course.price = None
        course.access_url = None
        course.remote_price = Decimal('3500')

        assert course.missing_for_publication == []
        assert course.can_be_published is True

    def test_course_without_any_price_is_not_publishable(self, course):
        course.price = None
        course.remote_price = None
        assert 'ціна' in course.missing_for_publication


# ----------------------------- черга довидачі -----------------------------

class TestPendingProvisioning:
    """Відлік -- від оплати, а не від оформлення замовлення."""

    def _paid(self, user, course, *, created_ago_h, paid_ago_min):
        from datetime import timedelta

        from app.models.mixins import utcnow

        item = OnlineEnrollment(
            user_id=user.id, online_course_id=course.id,
            payment_amount=Decimal('4500'), payment_status='paid',
            status='active',
        )
        db.session.add(item)
        db.session.flush()
        item.created_at = utcnow() - timedelta(hours=created_ago_h)
        item.paid_at = utcnow() - timedelta(minutes=paid_ago_min)
        db.session.flush()
        return item

    def test_just_paid_old_order_is_not_picked_up(self, user, course):
        """Рахунок виставили тиждень тому, оплатили щойно.

        Раніше таке замовлення джоба забирала одразу -- і видавала другий
        токен паралельно з callback-ом, гасячи посилання, яке щойно пішло
        листом.
        """
        self._paid(user, course, created_ago_h=168, paid_ago_min=1)

        assert sintegrum_access.pending_provisioning() == []

    def test_order_paid_long_ago_is_picked_up(self, user, course):
        stuck = self._paid(user, course, created_ago_h=168, paid_ago_min=30)

        assert stuck in sintegrum_access.pending_provisioning()

    def test_order_without_paid_at_falls_back_to_created_at(self, user, course):
        """У давніх і проставлених руками замовлень paid_at може бути порожнім."""
        stuck = self._paid(user, course, created_ago_h=2, paid_ago_min=0)
        stuck.paid_at = None
        db.session.flush()

        assert stuck in sintegrum_access.pending_provisioning()


# ----------------------------- реєстр учнів -----------------------------

class TestKnownStudentId:
    """Свій запис про учня надійніший за пошук на боці партнера."""

    def test_returns_id_from_previous_order(self, user, course):
        previous = OnlineEnrollment(
            user_id=user.id, online_course_id=course.id,
            payment_amount=Decimal('4500'), payment_status='paid',
            status='cancelled', sintegrum_student_id=77,
        )
        db.session.add(previous)
        db.session.flush()

        assert sintegrum_access.known_student_id(user.id) == 77

    def test_returns_none_for_first_purchase(self, user):
        assert sintegrum_access.known_student_id(user.id) is None

    def test_provision_does_not_ask_partner_when_id_is_known(self, user, course,
                                                             monkeypatch):
        """Повторна покупка не має заводити другого учня на той самий email."""
        previous = OnlineEnrollment(
            user_id=user.id, online_course_id=course.id,
            payment_amount=Decimal('4500'), payment_status='paid',
            status='cancelled', sintegrum_student_id=77,
        )
        db.session.add(previous)
        db.session.flush()

        second_course = OnlineCourse(
            sintegrum_id=98765, remote_name='Другий курс',
            slug=f'second-{uuid4().hex[:8]}', price=Decimal('3000'),
            is_published=True,
        )
        db.session.add(second_course)
        db.session.flush()

        order = OnlineEnrollment(
            user_id=user.id, online_course_id=second_course.id,
            payment_amount=Decimal('3000'), payment_status='paid',
            status='active',
        )
        db.session.add(order)
        db.session.flush()

        calls = []

        class _Client:
            def find_student_by_email(self, email):
                calls.append('find')
                raise AssertionError('партнера питати не мали')

            def create_student(self, **kw):
                calls.append('create')
                raise AssertionError('другого учня заводити не мали')

            def assign_course(self, student_id, course_id):
                calls.append(('assign', student_id, course_id))
                return SimpleNamespace(ok=True, error=None)

            def assigned_positions(self, user_id):
                return SimpleNamespace(
                    ok=True, error=None,
                    data=[{'user_id': user_id, 'position_id': 98765}])

        provider = sintegrum_access.StudentApiProvider(
            client=_Client(), settings=SimpleNamespace(
                sintegrum_company_alias='acme'),
        )
        monkeypatch.setattr(sintegrum_access, 'get_provider',
                            lambda course=None, settings=None: provider)

        sintegrum_access.provision(order, commit=False)

        assert calls == [('assign', 77, 98765)]  # партнера про пошук не питали
        assert order.sintegrum_student_id == 77


# ------------------- свіжість даних під блокуванням -------------------

class TestLockedReadIsFresh:
    """with_for_update() бере лок, але сам по собі НЕ оновлює об'єкт.

    Без populate_existing() SQLAlchemy віддає той самий екземпляр з
    identity map, і перевірка переходу дивиться на стан, якого в базі вже
    немає. Наслідок був би дорогий: оплата проводиться вдруге, у журналі
    з'являється другий запис, а видача доступу випускає новий токен --
    гасячи посилання, яке щойно пішло листом.
    """

    def _mark_paid_behind_the_orm(self, enrollment):
        """Імітація callback-а, що зафіксував оплату в іншому з'єднанні."""
        from sqlalchemy import text

        db.session.execute(
            text('UPDATE online_enrollments SET payment_status = :s '
                 'WHERE id = :i'),
            {'s': 'paid', 'i': enrollment.id},
        )

    def test_status_check_sees_payment_that_landed_meanwhile(self, ops,
                                                             enrollment):
        ops.liqpay.check_status.return_value = {
            'status': 'success', 'payment_id': 'pay-1', 'amount': 4500,
        }
        before = PaymentTransaction.query.count()
        self._mark_paid_behind_the_orm(enrollment)

        ok, msg = ops.check_enrollment_and_update(enrollment)

        assert ok is True
        assert msg == 'no-op transition'
        # Другого запису в журналі не з'явилось: оплату вже провів callback.
        assert PaymentTransaction.query.count() == before

    def test_second_provisioning_does_not_replace_a_live_token(self, ops,
                                                               enrollment):
        """Токен, уже надісланий листом, не має гаснути через гонку."""
        ops.update_enrollment_status(enrollment, 'paid', 'pay-1', amount=4500)
        issued = enrollment.access_token
        assert issued

        ops.liqpay.check_status.return_value = {
            'status': 'success', 'payment_id': 'pay-1', 'amount': 4500,
        }
        ops.check_enrollment_and_update(enrollment)

        db.session.refresh(enrollment)
        assert enrollment.access_token == issued
        assert enrollment.access_issued_count == 1


# ----------------------------- нагадування про курс -----------------------------

class TestAccessReminders:
    """Курс без дати легко відкласти "на потім" і забути."""

    def _provisioned(self, user, course, *, days_ago, opened=False):
        from datetime import timedelta

        from app.models.mixins import utcnow

        item = OnlineEnrollment(
            user_id=user.id, online_course_id=course.id,
            payment_amount=Decimal('4500'), payment_status='paid',
            status='active', access_token='tok', provisioned_at=(
                utcnow() - timedelta(days=days_ago)),
        )
        if opened:
            item.access_last_opened_at = utcnow()
        db.session.add(item)
        db.session.commit()
        return item

    def _run(self, monkeypatch, days=3):
        from app.models.site_settings import SiteSettings
        from app.services import scheduler_service
        from app.services.email_service import EmailService

        settings = SiteSettings.get()
        settings.sintegrum_access_reminder_days = days
        db.session.commit()

        sent = []
        monkeypatch.setattr(
            EmailService, 'send_online_access_reminder',
            staticmethod(lambda enrollment: sent.append(enrollment.id)),
        )
        scheduler_service._send_online_access_reminders()
        return sent

    def test_reminds_about_an_untouched_course(self, user, course, monkeypatch):
        order = self._provisioned(user, course, days_ago=5)

        assert self._run(monkeypatch) == [order.id]
        db.session.refresh(order)
        assert order.access_reminder_sent_at is not None

    def test_does_not_remind_twice(self, user, course, monkeypatch):
        self._provisioned(user, course, days_ago=5)

        self._run(monkeypatch)
        assert self._run(monkeypatch) == []

    def test_silent_about_a_course_already_opened(self, user, course,
                                                  monkeypatch):
        self._provisioned(user, course, days_ago=5, opened=True)

        assert self._run(monkeypatch) == []

    def test_waits_for_the_configured_period(self, user, course, monkeypatch):
        self._provisioned(user, course, days_ago=1)

        assert self._run(monkeypatch, days=3) == []

    def test_zero_days_turns_reminders_off(self, user, course, monkeypatch):
        self._provisioned(user, course, days_ago=30)

        assert self._run(monkeypatch, days=0) == []


# ------------------- звірка призначення на боці партнера -------------------

class TestAssignmentIsConfirmed:
    """Інцидент 20.08.2026: оплачено, "видано", а курсу в людини немає.

    `POST .../positions/...` відповідає порожнім 200 -- це "запит прийнято",
    а не "людина бачить курс". Без звірки будь-яке непорозуміння виглядало
    як успіх: замовлення позначалось виданим, лист ішов, покупець відкривав
    платформу й нічого там не знаходив.
    """

    def _provider(self, app, **overrides):
        return TestStudentApiProvider()._provider(app, **overrides)

    def test_silence_from_partner_is_not_success(self, app, enrollment):
        """Партнер прийняв запит, але курс у призначених не з'явився."""
        from app.services.sintegrum_client import SintegrumResult

        enrollment.course.access_url = None
        db.session.flush()
        provider, _calls = self._provider(
            app, progress=SintegrumResult(ok=True, data=[]))

        with pytest.raises(sintegrum_access.AccessProvisionError) as exc:
            provider.provision(enrollment)

        assert 'не з\'явився' in str(exc.value)

    def test_someone_elses_course_is_not_ours(self, app, enrollment):
        from app.services.sintegrum_client import SintegrumResult

        enrollment.course.access_url = None
        db.session.flush()
        provider, _calls = self._provider(app, progress=SintegrumResult(
            ok=True, data=[{'user_id': 777, 'position_id': 999999}]))

        with pytest.raises(sintegrum_access.AccessProvisionError):
            provider.provision(enrollment)

    def test_unreachable_partner_does_not_block_the_buyer(self, app, enrollment):
        """Наша перевірка не має ставати новою причиною відмови.

        Краще видати доступ і не знати напевно, ніж не видати через те, що
        звірка не відповіла.
        """
        from app.services.sintegrum_client import SintegrumResult

        enrollment.course.access_url = None
        db.session.flush()
        provider, _calls = self._provider(app, progress=SintegrumResult(
            ok=False, error='таймаут'))

        result = provider.provision(enrollment)

        assert result.student_id == 777

    def test_unexpected_shape_does_not_block_the_buyer(self, app, enrollment):
        from app.services.sintegrum_client import SintegrumResult

        enrollment.course.access_url = None
        db.session.flush()
        provider, _calls = self._provider(app, progress=SintegrumResult(
            ok=True, data={'unexpected': 'object'}))

        assert provider.provision(enrollment).student_id == 777

    def test_failed_confirmation_leaves_the_order_visibly_stuck(
            self, ops, enrollment, monkeypatch):
        """Замовлення лишається в списку "оплачено без доступу" з причиною."""
        from app.services.sintegrum_client import SintegrumResult

        enrollment.course.access_url = None
        db.session.flush()
        provider, _calls = TestStudentApiProvider()._provider(
            None, progress=SintegrumResult(ok=True, data=[]))
        monkeypatch.setattr(sintegrum_access, 'get_provider',
                            lambda course=None, settings=None: provider)

        ok, _msg = ops.update_enrollment_status(
            enrollment, 'paid', 'pay-1', amount=4500)
        db.session.refresh(enrollment)

        assert ok is True
        assert enrollment.payment_status == 'paid'
        assert enrollment.provisioned_at is None
        assert enrollment.access_token is None
        assert 'не з\'явився' in (enrollment.provision_error or '')


class TestAlreadyAssigned:
    """Сценарій ONL-5: партнер відмовляє, бо курс уже призначено.

    422 «Комбінацію 273-32 з User Id and Position Id уже використано»
    означає, що потрібний стан ДОСЯГНУТО. Трактувати це як збій -- лишити
    людину без доступу назавжди: кожна наступна спроба отримає те саме 422,
    а в адмінці й далі світитиметься «Не видано» з кнопкою «Видати доступ».
    """

    def _result(self, **kw):
        from app.services.sintegrum_client import SintegrumResult

        return SintegrumResult(**kw)

    def test_422_with_confirmation_is_success(self, app, enrollment):
        enrollment.course.access_url = None
        db.session.flush()
        provider, calls = TestStudentApiProvider()._provider(
            app,
            assign=self._result(ok=False, http_status=422,
                                error='Sintegrum 422: уже використано'),
            progress=self._result(ok=True, data=[
                {'user_id': 777, 'position_id': enrollment.course.sintegrum_id},
            ]),
        )

        result = provider.provision(enrollment)

        assert result.student_id == 777
        assert ('progress', 777) in calls

    def test_422_without_confirmation_is_still_success(self, app, enrollment):
        """Звірка не відповіла -- віримо самому партнеру: пара вже існує."""
        enrollment.course.access_url = None
        db.session.flush()
        provider, _calls = TestStudentApiProvider()._provider(
            app,
            assign=self._result(ok=False, http_status=422, error='уже використано'),
            progress=self._result(ok=False, error='таймаут'),
        )

        assert provider.provision(enrollment).student_id == 777

    def test_other_failure_without_confirmation_is_an_error(self, app, enrollment):
        """500 -- це справді збій, а не «вже зроблено»."""
        enrollment.course.access_url = None
        db.session.flush()
        provider, _calls = TestStudentApiProvider()._provider(
            app,
            assign=self._result(ok=False, http_status=500, error='Sintegrum 500'),
            progress=self._result(ok=False, error='таймаут'),
        )

        with pytest.raises(sintegrum_access.AccessProvisionError):
            provider.provision(enrollment)

    def test_order_becomes_provisioned_after_the_fix(self, ops, enrollment,
                                                     monkeypatch):
        """Те, заради чого все: рядок в адмінці перестає брехати."""
        enrollment.course.access_url = None
        db.session.flush()
        provider, _calls = TestStudentApiProvider()._provider(
            None,
            assign=self._result(ok=False, http_status=422, error='уже використано'),
            progress=self._result(ok=True, data=[
                {'user_id': 777, 'position_id': enrollment.course.sintegrum_id},
            ]),
        )
        monkeypatch.setattr(sintegrum_access, 'get_provider',
                            lambda course=None, settings=None: provider)

        ops.update_enrollment_status(enrollment, 'paid', 'pay-1', amount=4500)
        db.session.refresh(enrollment)

        assert enrollment.provisioned_at is not None
        assert enrollment.access_token
        assert enrollment.provision_error is None
