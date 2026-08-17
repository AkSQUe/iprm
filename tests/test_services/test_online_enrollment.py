"""Оплата онлайн-курсів: перехід статусів і видача доступу.

Найважливіше тут -- порядок: спершу фіксується оплата, потім видається
доступ. Якщо переставити, збій видачі відкотив би оплату, і система
вважала б неоплаченим замовлення, за яке гроші вже прийшли.
"""
from decimal import Decimal
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
                return overrides.get('assign', SintegrumResult(ok=True, data={}))

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

        assert [c[0] for c in calls] == ['find', 'create', 'assign']
        assert calls[-1] == ('assign', 777, enrollment.course.sintegrum_id)
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

        assert [c[0] for c in calls] == ['assign']

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
