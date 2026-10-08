"""Дата оплати при ручній зміні статусу реєстрації.

MM Medic закриває місяць, відбираючи оплати за paid_at. Ручні шляхи
(випадайка в таблиці, форма учасника, безкоштовна реєстрація) довго ставили
paid без дати -- і такі оплати не потрапляли в жоден звіт. Правило одне на
всі шляхи -- apply_manual_payment_status; тут перевіряється воно саме і
сервісні шляхи, що ним користуються. HTTP-шляхи -- у
tests/test_routes/test_admin_manual_payment.py.
"""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import PAID_AT_DATE, PAID_AT_DATETIME
from app.models.payment_transaction import PaymentTransaction
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import participant_service, registration_service
from app.services.payment_ops import apply_manual_payment_status, paid_moment
from app.utils import KYIV, ensure_utc, to_kyiv


def _uid():
    return uuid4().hex[:8]


def _instance(price=1500):
    course = Course(slug=f'mp-{_uid()}', title='Manual Pay', base_price=price,
                    is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='active',
                          event_format='offline', price=price)
    db.session.add(inst)
    db.session.flush()
    return inst


def _reg(payment_status='unpaid', paid_at=None, amount=1500):
    user = User.create_with_password(
        f'mp-{_uid()}@test.com', 'password123', first_name='Іван', last_name='Петренко',
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=_instance(amount).id,
        phone='+380501112233', specialty='S', workplace='W',
        status='confirmed', payment_status=payment_status,
        payment_amount=amount, payment_method='invoice', paid_at=paid_at,
        paid_at_precision='datetime' if paid_at else None,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


def _manual_txns(reg):
    return PaymentTransaction.query.filter_by(
        registration_id=reg.id, source='manual',
    ).order_by(PaymentTransaction.id).all()


def _kyiv_today():
    return to_kyiv(datetime.now(timezone.utc)).date()


class TestRule:
    def test_unpaid_to_paid_sets_date_and_logs(self, app):
        reg = _reg()
        before = datetime.now(timezone.utc)

        assert apply_manual_payment_status(reg, 'paid', actor='a@test.com') is True
        db.session.flush()

        assert reg.payment_status == 'paid'
        assert ensure_utc(reg.paid_at) >= before - timedelta(seconds=1)
        assert reg.paid_at_precision == PAID_AT_DATETIME
        txns = _manual_txns(reg)
        assert len(txns) == 1
        assert txns[0].mapped_status == 'paid'
        assert float(txns[0].amount) == 1500.0
        assert txns[0].raw_payload['actor'] == 'a@test.com'
        assert txns[0].raw_payload['previous_status'] == 'unpaid'

    def test_paid_to_unpaid_clears_date(self, app):
        reg = _reg('paid', paid_at=datetime(2026, 9, 10, 9, tzinfo=timezone.utc))
        apply_manual_payment_status(reg, 'unpaid')
        assert reg.paid_at is None
        assert reg.paid_at_precision is None
        assert _manual_txns(reg)[-1].mapped_status == 'unpaid'

    def test_paid_to_pending_clears_date(self, app):
        reg = _reg('paid', paid_at=datetime(2026, 9, 10, 9, tzinfo=timezone.utc))
        apply_manual_payment_status(reg, 'pending')
        assert reg.paid_at is None

    def test_paid_to_refunded_keeps_date(self, app):
        """Оплата відбулась -- повернення її не скасовує в часі."""
        paid_at = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
        reg = _reg('paid', paid_at=paid_at)
        apply_manual_payment_status(reg, 'refunded')
        assert ensure_utc(reg.paid_at) == paid_at
        assert reg.paid_at_precision == PAID_AT_DATETIME

    def test_paid_to_paid_does_not_overwrite(self, app):
        paid_at = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
        reg = _reg('paid', paid_at=paid_at)

        assert apply_manual_payment_status(reg, 'paid') is False
        assert ensure_utc(reg.paid_at) == paid_at
        assert _manual_txns(reg) == []

    def test_resave_with_same_day_does_not_move_time(self, app):
        """Форма показує київську дату збереженої оплати; збереження її ж
        не має пересувати оплату на полудень."""
        paid_at = datetime(2026, 9, 10, 6, 30, tzinfo=timezone.utc)
        reg = _reg('paid', paid_at=paid_at)

        assert apply_manual_payment_status(
            reg, 'paid', paid_on=to_kyiv(paid_at).date()) is False
        assert ensure_utc(reg.paid_at) == paid_at

    def test_paid_without_date_stays_without_date(self, app):
        """Старий рядок без дати: повторне збереження дату НЕ вигадує."""
        reg = _reg('paid')
        assert apply_manual_payment_status(reg, 'paid') is False
        assert reg.paid_at is None

    def test_explicit_date_is_noon_kyiv(self, app):
        day = _kyiv_today() - timedelta(days=20)
        reg = _reg()
        apply_manual_payment_status(reg, 'paid', paid_on=day)
        expected = datetime.combine(day, time(12), tzinfo=KYIV)
        assert ensure_utc(reg.paid_at) == expected.astimezone(timezone.utc)
        assert reg.paid_at_precision == PAID_AT_DATE
        assert _manual_txns(reg)[0].raw_payload['paid_at_precision'] == PAID_AT_DATE

    def test_correcting_the_day_changes_precision(self, app):
        """Позначка "зараз", потім дата з виписки: час стає невідомим."""
        reg = _reg()
        apply_manual_payment_status(reg, 'paid')
        apply_manual_payment_status(
            reg, 'paid', paid_on=_kyiv_today() - timedelta(days=3))
        assert reg.paid_at_precision == PAID_AT_DATE

    def test_future_date_is_rejected(self, app):
        reg = _reg()
        with pytest.raises(ValueError):
            apply_manual_payment_status(
                reg, 'paid', paid_on=_kyiv_today() + timedelta(days=2))


class TestPaidMoment:
    NOW = datetime(2026, 10, 8, 7, 15, tzinfo=timezone.utc)

    def test_without_date_is_now_with_time(self):
        assert paid_moment(now=self.NOW) == (self.NOW, PAID_AT_DATETIME)

    def test_today_is_now_with_time(self):
        assert paid_moment(date(2026, 10, 8), now=self.NOW) == (
            self.NOW, PAID_AT_DATETIME)

    def test_past_day_is_noon_kyiv_without_time(self):
        moment, precision = paid_moment(date(2026, 9, 15), now=self.NOW)
        assert moment == datetime(2026, 9, 15, 12, tzinfo=KYIV)
        assert precision == PAID_AT_DATE

    def test_first_of_month_stays_in_its_month_in_utc(self):
        """Північ за Києвом -- це вчорашній вечір в UTC: оплата 1-го числа
        лягла б у попередній місяць."""
        moment, _ = paid_moment(date(2026, 10, 1), now=self.NOW)
        assert moment.astimezone(timezone.utc).date() == date(2026, 10, 1)

    def test_future_day_is_rejected(self):
        with pytest.raises(ValueError):
            paid_moment(date(2026, 10, 10), now=self.NOW)


class TestPrecisionCheck:
    """CHECK у БД -- остання лінія: дата без точності і точність без дати."""

    def test_precision_without_date_is_rejected(self, app):
        reg = _reg()
        reg.paid_at_precision = PAID_AT_DATE
        with pytest.raises(Exception):
            db.session.flush()
        db.session.rollback()

    def test_date_without_precision_is_rejected(self, app):
        reg = _reg()
        reg.paid_at = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
        with pytest.raises(Exception):
            db.session.flush()
        db.session.rollback()

    def test_unknown_precision_is_rejected_in_python(self, app):
        reg = _reg()
        with pytest.raises(ValueError):
            reg.set_paid_at(datetime(2026, 9, 10, 9, tzinfo=timezone.utc), 'hour')


class TestParticipantService:
    def _data(self, instance_id, **over):
        data = {
            'instance_id': instance_id,
            'last_name': 'Петренко', 'first_name': 'Іван', 'middle_name': None,
            'email': None, 'phone': '+380501112233',
            'participant_type': None, 'birth_date': None, 'education': None,
            'workplace': None, 'position': None, 'specializations': [],
            'status': 'confirmed', 'payment_status': 'unpaid',
            'payment_amount': 1500, 'attended': False,
            'cpd_points_awarded': None, 'experience_years': None,
            'license_number': None, 'admin_notes': None,
        }
        data.update(over)
        return data

    def test_edit_unpaid_to_paid_sets_date_and_logs(self, app):
        reg = _reg()
        participant_service.upsert_participant(
            self._data(reg.instance_id, payment_status='paid'), reg=reg)
        db.session.flush()

        assert reg.paid_at is not None
        assert [t.mapped_status for t in _manual_txns(reg)] == ['paid']

    def test_create_as_paid_sets_date_and_logs(self, app):
        """Нова реєстрація ще не має id -- журнал пишеться після flush."""
        inst = _instance()
        reg, created = participant_service.upsert_participant(
            self._data(inst.id, payment_status='paid'), reg=None)
        db.session.flush()

        assert created is True
        assert reg.paid_at is not None
        assert [t.mapped_status for t in _manual_txns(reg)] == ['paid']

    def test_create_unpaid_writes_nothing(self, app):
        inst = _instance()
        reg, _ = participant_service.upsert_participant(
            self._data(inst.id), reg=None)
        db.session.flush()

        assert reg.payment_status == 'unpaid'
        assert reg.paid_at is None
        assert reg.paid_at_precision is None
        assert _manual_txns(reg) == []

    def test_date_from_form_is_kept(self, app):
        day = _kyiv_today() - timedelta(days=10)
        reg = _reg()
        participant_service.upsert_participant(
            self._data(reg.instance_id, payment_status='paid', paid_on=day),
            reg=reg)
        assert to_kyiv(reg.paid_at).date() == day
        assert reg.paid_at_precision == PAID_AT_DATE

    def test_future_date_is_a_participant_error(self, app):
        reg = _reg()
        with pytest.raises(participant_service.ParticipantError):
            participant_service.upsert_participant(
                self._data(reg.instance_id, payment_status='paid',
                           paid_on=_kyiv_today() + timedelta(days=2)),
                reg=reg)


class TestFreeRegistration:
    FORM = {'phone': '+380501234567', 'specialty': 'Dermatologist',
            'workplace': 'City Hospital'}

    def _user(self):
        user = User.create_with_password(
            f'mp-{_uid()}@test.com', 'password123', first_name='A', last_name='B')
        db.session.flush()
        return user

    def test_new_free_registration_gets_paid_at(self, app):
        user = self._user()
        reg, is_free = registration_service.create_or_reactivate(
            user.id, _instance(price=0), self.FORM)
        db.session.flush()

        assert is_free is True
        assert reg.payment_status == 'paid'
        assert reg.paid_at is not None
        assert reg.paid_at_precision == PAID_AT_DATETIME
        assert [t.mapped_status for t in _manual_txns(reg)] == ['paid']

    def test_reactivated_free_registration_gets_paid_at(self, app):
        """Раніше реактивація ставила paid і тут же обнуляла paid_at."""
        user = self._user()
        inst = _instance(price=0)
        old = EventRegistration(
            user_id=user.id, instance_id=inst.id, phone='+380', specialty='S',
            workplace='W', status='cancelled', payment_status='unpaid',
        )
        db.session.add(old)
        db.session.flush()

        reg, _ = registration_service.create_or_reactivate(
            user.id, inst, self.FORM, existing=old)
        db.session.flush()

        assert reg.id == old.id
        assert reg.payment_status == 'paid'
        assert reg.paid_at is not None
        assert reg.paid_at_precision == PAID_AT_DATETIME
        assert [t.mapped_status for t in _manual_txns(reg)] == ['paid']

    def test_paid_event_registration_stays_unpaid(self, app):
        user = self._user()
        reg, is_free = registration_service.create_or_reactivate(
            user.id, _instance(price=1500), self.FORM)
        db.session.flush()

        assert is_free is False
        assert reg.payment_status == 'unpaid'
        assert reg.paid_at is None
        assert reg.paid_at_precision is None
        assert _manual_txns(reg) == []
