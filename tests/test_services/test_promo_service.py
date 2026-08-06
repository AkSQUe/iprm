"""Тести промокодів: розрахунок знижки, валідація, ліміти, анулювання.

Перевіряємо і сам promo_service, і його зчеплення з registration_service
(знижка має доїжджати до payment_amount, а 100% -- робити реєстрацію
безкоштовною з усіма наслідками).
"""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.promo_code import PromoCode, PromoRedemption
from app.models.user import User
from app.services import promo_service, registration_service
from app.services.promo_service import PromoError


@pytest.fixture
def user(app):
    u = User.create_with_password(
        f'promo-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Promo', last_name='User',
    )
    db.session.flush()
    return u


def _make_instance(price=5000):
    course = Course(title='Promo Course', slug=f'promo-{uuid4().hex[:6]}',
                    is_active=True, base_price=price)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='active', price=price)
    db.session.add(inst)
    db.session.flush()
    return inst


@pytest.fixture
def instance(app):
    return _make_instance()


def _make_promo(code='Дмитро', **kwargs):
    kwargs.setdefault('discount_type', 'percent')
    kwargs.setdefault('discount_value', Decimal('50'))
    kwargs.setdefault('per_user_limit', 1)
    promo = PromoCode(
        code=code, code_norm=promo_service.normalize_code(code), **kwargs,
    )
    db.session.add(promo)
    db.session.flush()
    return promo


@pytest.fixture
def form_data():
    return {
        'phone': '+380501234567',
        'specialty': 'Dermatologist',
        'workplace': 'City Hospital',
        'experience_years': 3,
        'license_number': 'LIC-777',
    }


class TestNormalizeCode:

    def test_case_and_spaces_are_irrelevant(self):
        assert (promo_service.normalize_code('  ДМИТРО ')
                == promo_service.normalize_code('дмитро'))

    def test_internal_spaces_stripped(self):
        assert promo_service.normalize_code('SPRING 2026') == 'spring2026'

    def test_empty(self):
        assert promo_service.normalize_code(None) == ''


class TestDiscountMath:

    def test_percent(self):
        promo = _make_promo(discount_value=Decimal('20'))
        assert promo.discount_for(Decimal('5000')) == Decimal('1000.00')
        assert promo.final_for(Decimal('5000')) == Decimal('4000.00')

    def test_percent_100_is_free(self):
        promo = _make_promo(discount_value=Decimal('100'))
        assert promo.final_for(Decimal('5000')) == Decimal('0.00')

    def test_fixed_amount(self):
        promo = _make_promo(discount_type='amount', discount_value=Decimal('500'))
        assert promo.final_for(Decimal('5000')) == Decimal('4500.00')

    def test_fixed_amount_never_below_zero(self):
        promo = _make_promo(discount_type='amount', discount_value=Decimal('9000'))
        assert promo.discount_for(Decimal('5000')) == Decimal('5000.00')
        assert promo.final_for(Decimal('5000')) == Decimal('0.00')

    def test_rounds_to_kopiyky(self):
        promo = _make_promo(discount_value=Decimal('33.33'))
        assert promo.discount_for(Decimal('1000')) == Decimal('333.30')


class TestValidate:

    def test_unknown_code(self, instance):
        with pytest.raises(PromoError):
            promo_service.validate('немає-такого', instance=instance, amount=100)

    def test_case_insensitive_lookup(self, instance):
        _make_promo('Дмитро')
        promo, discount, final = promo_service.validate(
            'дМиТрО', instance=instance, amount=Decimal('1000'),
        )
        assert promo.code == 'Дмитро'
        assert (discount, final) == (Decimal('500.00'), Decimal('500.00'))

    def test_disabled(self, instance):
        _make_promo('off', is_active=False)
        with pytest.raises(PromoError):
            promo_service.validate('off', instance=instance, amount=100)

    def test_expired(self, instance):
        _make_promo('old', valid_until=utcnow() - timedelta(days=1))
        with pytest.raises(PromoError):
            promo_service.validate('old', instance=instance, amount=100)

    def test_not_started(self, instance):
        _make_promo('future', valid_from=utcnow() + timedelta(days=1))
        with pytest.raises(PromoError):
            promo_service.validate('future', instance=instance, amount=100)

    def test_exhausted(self, instance):
        _make_promo('used', max_uses=1, used_count=1)
        with pytest.raises(PromoError):
            promo_service.validate('used', instance=instance, amount=100)

    def test_scope_other_course(self, instance):
        other = _make_instance()
        _make_promo('narrow', course_id=other.course_id)
        with pytest.raises(PromoError):
            promo_service.validate('narrow', instance=instance, amount=100)

    def test_scope_matching_course(self, instance):
        _make_promo('mine', course_id=instance.course_id)
        promo, _d, _f = promo_service.validate('mine', instance=instance, amount=100)
        assert promo.course_id == instance.course_id

    def test_scope_specific_instance(self, instance):
        _make_promo('one-date', instance_id=instance.id)
        promo, _d, _f = promo_service.validate('one-date', instance=instance, amount=100)
        assert promo.instance_id == instance.id

        elsewhere = _make_instance()
        with pytest.raises(PromoError):
            promo_service.validate('one-date', instance=elsewhere, amount=100)

    def test_free_event_rejected(self, instance):
        _make_promo('free-already')
        with pytest.raises(PromoError):
            promo_service.validate('free-already', instance=instance, amount=0)


class TestApplyToRegistration:

    def test_discount_lands_on_payment_amount(self, user, instance, form_data):
        promo = _make_promo('half', discount_value=Decimal('50'))
        reg, is_free = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()

        assert is_free is False
        assert reg.payment_amount == Decimal('2500.00')
        assert reg.discount_amount == Decimal('2500.00')
        assert reg.amount_before_discount == Decimal('5000.00')
        assert reg.promo_code_id == promo.id
        assert promo.used_count == 1

    def test_full_discount_confirms_registration(self, user, instance, form_data):
        promo = _make_promo('vip', discount_value=Decimal('100'))
        reg, is_free = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()

        assert is_free is True
        assert reg.payment_amount == Decimal('0.00')
        assert reg.status == 'confirmed'
        assert reg.payment_status == 'paid'
        assert reg.place_number == 1

    def test_redemption_row_snapshots_amounts(self, user, instance, form_data):
        promo = _make_promo('snap', discount_type='amount',
                            discount_value=Decimal('1500'))
        reg, _ = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()

        row = PromoRedemption.query.filter_by(registration_id=reg.id).one()
        assert row.original_amount == Decimal('5000.00')
        assert row.discount_amount == Decimal('1500.00')
        assert row.final_amount == Decimal('3500.00')
        assert row.status == 'applied'
        assert row.user_id == user.id

    def test_second_apply_replaces_first(self, user, instance, form_data):
        first = _make_promo('first', discount_value=Decimal('10'))
        second = _make_promo('second', discount_value=Decimal('30'))
        reg, _ = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=first,
        )
        db.session.flush()

        promo_service.apply_to_registration(second, reg, Decimal('5000'))
        db.session.flush()

        assert first.used_count == 0
        assert second.used_count == 1
        assert reg.promo_code_id == second.id
        assert reg.payment_amount == Decimal('3500.00')
        # Старе списання лишається в історії як анульоване.
        rows = PromoRedemption.query.filter_by(registration_id=reg.id).all()
        assert len(rows) == 2
        by_status = {r.status: r for r in rows}
        assert by_status['voided'].promo_code_id == first.id
        assert by_status['applied'].promo_code_id == second.id


class TestLimits:

    def test_per_user_limit_blocks_second_use(self, user, instance, form_data):
        promo = _make_promo('once-per-person', per_user_limit=1)
        reg, _ = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()

        other_instance = _make_instance()
        with pytest.raises(PromoError):
            promo_service.validate(
                'once-per-person', instance=other_instance,
                amount=Decimal('5000'), user_id=user.id,
            )

    def test_per_user_limit_ignores_own_registration(self, user, instance, form_data):
        promo = _make_promo('resave', per_user_limit=1)
        reg, _ = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()

        # Повторне збереження тієї самої реєстрації не має впиратись у ліміт.
        promo_service.assert_user_limit(
            promo, user.id, ignore_registration_id=reg.id,
        )

    def test_unlimited_per_user(self, user, instance, form_data):
        promo = _make_promo('unlimited', per_user_limit=None)
        registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()
        promo_service.assert_user_limit(promo, user.id)

    def test_max_uses_exhausts_code(self, user, instance, form_data):
        promo = _make_promo('two-seats', max_uses=2, per_user_limit=None)
        registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()
        assert promo.uses_left == 1

        second_user = User.create_with_password(
            f'promo2-{uuid4().hex[:6]}@test.com', 'password123',
        )
        db.session.flush()
        registration_service.create_or_reactivate(
            second_user.id, _make_instance(), form_data, promo=promo,
        )
        db.session.flush()

        assert promo.uses_left == 0
        assert promo.is_exhausted is True
        with pytest.raises(PromoError):
            promo_service.validate('two-seats', instance=instance, amount=5000)


class TestVoidAndDetach:

    def test_void_frees_the_seat(self, user, instance, form_data):
        promo = _make_promo('refundable', max_uses=1)
        reg, _ = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()
        assert promo.used_count == 1

        promo_service.void_for_registration(reg, reason='Повернення коштів')
        db.session.flush()

        assert promo.used_count == 0
        assert promo.is_exhausted is False
        # Знімок знижки на реєстрації лишається для звітів.
        assert reg.discount_amount == Decimal('2500.00')
        row = PromoRedemption.query.filter_by(registration_id=reg.id).one()
        assert row.status == 'voided'
        assert row.voided_at is not None

    def test_detach_clears_registration_snapshot(self, user, instance, form_data):
        promo = _make_promo('detachable')
        reg, _ = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()

        promo_service.detach(reg)
        db.session.flush()

        assert reg.promo_code_id is None
        assert reg.discount_amount is None
        assert promo.used_count == 0

    def test_sync_voids_on_refund(self, user, instance, form_data):
        promo = _make_promo('sync-refund')
        reg, _ = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()

        reg.payment_status = 'refunded'
        promo_service.sync_for_registration(reg)
        db.session.flush()
        assert promo.used_count == 0

    def test_sync_noop_while_unpaid(self, user, instance, form_data):
        promo = _make_promo('sync-noop')
        reg, _ = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()

        assert promo_service.sync_for_registration(reg) is None
        assert promo.used_count == 1


class TestRecountAndStats:

    def test_recount_fixes_drift(self, user, instance, form_data):
        promo = _make_promo('drifted')
        registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()

        promo.used_count = 17  # ручна правка в БД
        assert promo_service.recount(promo) == 1
        assert promo.used_count == 1

    def test_stats(self, user, instance, form_data):
        promo = _make_promo('stats', discount_value=Decimal('50'))
        reg, _ = registration_service.create_or_reactivate(
            user.id, instance, form_data, promo=promo,
        )
        db.session.flush()

        data = promo_service.stats(promo)
        assert data['applied'] == 1
        assert data['discount_total'] == Decimal('2500.00')
        assert data['paid_count'] == 0

        reg.payment_status = 'paid'
        db.session.flush()
        assert promo_service.stats(promo)['paid_count'] == 1
