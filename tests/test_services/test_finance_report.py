"""Виручка й зобов'язання за місяць (app.services.finance_report).

Оплата -- ще не виручка: гроші за захід, що попереду, ми винні учаснику.
Тести стережуть межу між "виконано" і "винні": місяць заходу, а не оплати;
київські межі місяця; залишок після повернень; онлайн-курс -- за видачею
доступу; оплата без дати -- окремо, а не мовчки в якомусь місяці.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.registration import EventRegistration
from app.models.user import User
from app.services.finance_report import build_report, month_bounds, parse_month

SEPT = date(2026, 9, 1)
OCT = date(2026, 10, 1)
NOW = datetime(2026, 10, 8, 9, tzinfo=timezone.utc)


def _uid():
    return uuid4().hex[:8]


def _user():
    user = User.create_with_password(
        f'fin-{_uid()}@test.com', 'password123', first_name='Іван', last_name='Петренко')
    db.session.flush()
    return user


def _instance(ends_at, starts_at=None):
    course = Course(title=f'Захід {_uid()}', slug=f'fin-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline',
                          start_date=starts_at or ends_at, end_date=ends_at)
    db.session.add(inst)
    db.session.flush()
    return inst


def _reg(instance, paid_at, amount=1000, refunded=0, status='paid'):
    reg = EventRegistration(
        user_id=_user().id, instance_id=instance.id, phone='+380501112233',
        specialty='S', workplace='W', status='confirmed', payment_status=status,
        payment_method='invoice', payment_amount=amount, refunded_amount=refunded,
    )
    if paid_at is not None:
        reg.set_paid_at(paid_at, 'datetime')
    db.session.add(reg)
    db.session.flush()
    return reg


def _ids(rows):
    return {row.order_id for row in rows}


class TestMonth:
    def test_bounds_are_kyiv(self):
        start, end = month_bounds(OCT)
        assert start == datetime(2026, 9, 30, 21, tzinfo=timezone.utc)
        assert end == datetime(2026, 10, 31, 22, tzinfo=timezone.utc)  # зимовий час

    def test_december_rolls_over(self):
        _, end = month_bounds(date(2026, 12, 1))
        assert end == datetime(2026, 12, 31, 22, tzinfo=timezone.utc)

    @pytest.mark.parametrize('raw', ['', None, '2026-13', 'вересень'])
    def test_bad_month_is_current(self, raw):
        assert parse_month(raw, today=date(2026, 10, 8)) == OCT

    def test_month_is_parsed(self):
        assert parse_month('2026-09') == SEPT


class TestEvents:
    def test_past_event_is_revenue_of_its_month(self, app):
        reg = _reg(_instance(datetime(2026, 9, 12, 15, tzinfo=timezone.utc)),
                   paid_at=datetime(2026, 9, 5, tzinfo=timezone.utc))

        report = build_report(SEPT, now=NOW)

        assert f'REG-{reg.id}' in _ids(report.revenue)
        assert f'REG-{reg.id}' not in _ids(report.liabilities)

    def test_september_payment_for_october_event(self, app):
        """Кредиторка на кінець вересня, виручка жовтня."""
        reg = _reg(_instance(datetime(2026, 10, 17, 15, tzinfo=timezone.utc)),
                   paid_at=datetime(2026, 9, 16, tzinfo=timezone.utc))
        order = f'REG-{reg.id}'

        september = build_report(SEPT, now=NOW)
        october_so_far = build_report(OCT, now=NOW)
        october_after = build_report(OCT, now=datetime(2026, 11, 2, tzinfo=timezone.utc))

        assert order in _ids(september.liabilities)
        assert order not in _ids(september.revenue)
        assert order in _ids(october_so_far.liabilities)   # 8.10 захід ще попереду
        assert order not in _ids(october_so_far.revenue)
        assert order in _ids(october_after.revenue)
        assert order not in _ids(october_after.liabilities)

    def test_payment_after_month_end_is_not_its_liability(self, app):
        reg = _reg(_instance(datetime(2026, 10, 17, tzinfo=timezone.utc)),
                   paid_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
        assert f'REG-{reg.id}' not in _ids(build_report(SEPT, now=NOW).liabilities)

    def test_event_ending_after_kyiv_midnight_belongs_to_next_month(self, app):
        """30.09 22:30 UTC -- це вже 1 жовтня за Києвом."""
        reg = _reg(_instance(datetime(2026, 9, 30, 22, 30, tzinfo=timezone.utc)),
                   paid_at=datetime(2026, 9, 20, tzinfo=timezone.utc))
        order = f'REG-{reg.id}'

        assert order not in _ids(build_report(SEPT, now=NOW).revenue)
        assert order in _ids(build_report(SEPT, now=NOW).liabilities)
        assert order in _ids(build_report(OCT, now=NOW).revenue)

    def test_amount_is_net_of_partial_refund(self, app):
        reg = _reg(_instance(datetime(2026, 9, 12, tzinfo=timezone.utc)),
                   paid_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
                   amount=7000, refunded=1750)

        row = next(r for r in build_report(SEPT, now=NOW).revenue
                   if r.order_id == f'REG-{reg.id}')

        assert row.amount == Decimal('5250')

    @pytest.mark.parametrize('status', ['refunded', 'unpaid', 'pending'])
    def test_not_kept_money_is_not_counted(self, app, status):
        reg = _reg(_instance(datetime(2026, 9, 12, tzinfo=timezone.utc)),
                   paid_at=datetime(2026, 9, 5, tzinfo=timezone.utc), status=status)
        report = build_report(SEPT, now=NOW)
        assert f'REG-{reg.id}' not in _ids(report.revenue) | _ids(report.liabilities)

    def test_free_registration_is_not_counted(self, app):
        reg = _reg(_instance(datetime(2026, 9, 12, tzinfo=timezone.utc)),
                   paid_at=datetime(2026, 9, 5, tzinfo=timezone.utc), amount=0)
        assert f'REG-{reg.id}' not in _ids(build_report(SEPT, now=NOW).revenue)

    def test_paid_without_date_is_reported_apart(self, app):
        reg = _reg(_instance(datetime(2026, 9, 12, tzinfo=timezone.utc)), paid_at=None)
        report = build_report(SEPT, now=NOW)

        assert f'REG-{reg.id}' in report.undated
        assert f'REG-{reg.id}' not in _ids(report.revenue)

    def test_event_without_dates_stays_a_liability(self, app):
        course = Course(title='Без дати', slug=f'fin-{_uid()}', is_active=True)
        db.session.add(course)
        db.session.flush()
        inst = CourseInstance(course_id=course.id, status='published', event_format='offline')
        db.session.add(inst)
        db.session.flush()
        reg = _reg(inst, paid_at=datetime(2026, 9, 5, tzinfo=timezone.utc))

        assert f'REG-{reg.id}' in _ids(build_report(SEPT, now=NOW).liabilities)

    def test_groups_sum_by_event(self, app):
        inst = _instance(datetime(2026, 9, 12, tzinfo=timezone.utc))
        paid = datetime(2026, 9, 5, tzinfo=timezone.utc)
        _reg(inst, paid, amount=1000)
        _reg(inst, paid, amount=1500)

        group = next(g for g in build_report(SEPT, now=NOW).revenue_groups
                     if g.title == inst.effective_title)

        assert (group.count, group.amount) == (2, Decimal('2500'))


class TestOnline:
    def _enrollment(self, paid_at, provisioned_at, amount=500):
        course = OnlineCourse(sintegrum_id=int(uuid4().int % 10_000_000),
                              remote_name='Онлайн', slug=f'fin-{_uid()}', price=amount)
        db.session.add(course)
        db.session.flush()
        item = OnlineEnrollment(user_id=_user().id, online_course_id=course.id,
                                payment_status='paid', payment_amount=amount,
                                provisioned_at=provisioned_at)
        item.set_paid_at(paid_at, 'datetime')
        db.session.add(item)
        db.session.flush()
        return item

    def test_access_given_is_revenue(self, app):
        moment = datetime(2026, 9, 10, 8, tzinfo=timezone.utc)
        item = self._enrollment(moment, moment + timedelta(minutes=1))

        report = build_report(SEPT, now=NOW)

        assert item.order_id in _ids(report.revenue)
        assert report.revenue_online_total >= Decimal('500')

    def test_access_not_given_is_liability(self, app):
        item = self._enrollment(datetime(2026, 9, 10, tzinfo=timezone.utc), None)
        assert item.order_id in _ids(build_report(SEPT, now=NOW).liabilities)


def _request(reg, status, code='standard', decided_at=None):
    from app.models.refund_request import RefundRequest

    item = RefundRequest(registration_id=reg.id, user_id=reg.user_id,
                         reason='Не зможу', status=status, quoted_code=code,
                         decided_at=decided_at)
    db.session.add(item)
    db.session.flush()
    return item


class TestWithdrawal:
    """Відмова учасника (погоджено 10.10.2026): утримане -- виручка на дату
    повернення, без повернення -- на дату скасування; поки заявка чекає
    рішення, уся сума -- зобов'язання. Різниця тарифу при перенесенні
    відмовою не є."""

    EVENT = datetime(2026, 9, 12, 15, tzinfo=timezone.utc)
    PAID = datetime(2026, 8, 20, tzinfo=timezone.utc)

    def _cancelled(self, cancelled_at, refunded=0, refunded_at=None):
        reg = _reg(_instance(self.EVENT), paid_at=self.PAID, refunded=refunded)
        reg.status = 'cancelled'
        db.session.flush()
        reg.cancelled_at = cancelled_at
        reg.refunded_at = refunded_at
        db.session.flush()
        return reg

    def test_no_refund_is_revenue_on_cancellation_day(self, app):
        reg = self._cancelled(datetime(2026, 8, 28, tzinfo=timezone.utc))
        order = f'REG-{reg.id}'

        assert order in _ids(build_report(date(2026, 8, 1), now=NOW).revenue)
        assert order not in _ids(build_report(SEPT, now=NOW).revenue)

    def test_partial_refund_is_revenue_on_refund_day(self, app):
        """Скасовано 10.09, повернули половину 05.10: утримане -- виручка
        жовтня, а на кінець вересня вся сума ще зобов'язання."""
        reg = self._cancelled(datetime(2026, 9, 10, tzinfo=timezone.utc), refunded=500,
                              refunded_at=datetime(2026, 10, 5, 9, tzinfo=timezone.utc))
        order = f'REG-{reg.id}'

        september = build_report(SEPT, now=NOW)
        october = build_report(OCT, now=NOW)

        assert order not in _ids(september.revenue)
        assert order in _ids(september.liabilities)
        row = next(r for r in october.revenue if r.order_id == order)
        assert row.amount == Decimal('500')

    def test_pending_request_is_a_liability_even_after_the_event(self, app):
        reg = _reg(_instance(self.EVENT), paid_at=self.PAID)
        _request(reg, 'new')
        order = f'REG-{reg.id}'

        report = build_report(SEPT, now=NOW)

        assert order not in _ids(report.revenue)
        assert order in _ids(report.liabilities)

    def test_approved_partial_refund_without_cancel_is_a_withdrawal(self, app):
        """Повернення за Політикою, а статус лишився «підтверджено»: людина
        однаково відмовилась -- виручка на дату повернення, не заходу."""
        reg = _reg(_instance(self.EVENT), paid_at=self.PAID, refunded=500)
        reg.refunded_at = datetime(2026, 10, 5, tzinfo=timezone.utc)
        _request(reg, 'approved', decided_at=datetime(2026, 10, 5, tzinfo=timezone.utc))
        order = f'REG-{reg.id}'

        assert order not in _ids(build_report(SEPT, now=NOW).revenue)
        assert order in _ids(build_report(OCT, now=NOW).revenue)

    def test_transfer_difference_is_not_a_withdrawal(self, app):
        reg = _reg(_instance(self.EVENT), paid_at=self.PAID)
        _request(reg, 'new', code='transfer_diff')

        assert f'REG-{reg.id}' in _ids(build_report(SEPT, now=NOW).revenue)

    def test_rejected_request_changes_nothing(self, app):
        reg = _reg(_instance(self.EVENT), paid_at=self.PAID)
        _request(reg, 'rejected', decided_at=datetime(2026, 9, 1, tzinfo=timezone.utc))

        assert f'REG-{reg.id}' in _ids(build_report(SEPT, now=NOW).revenue)

    def test_withdrawals_are_a_separate_group(self, app):
        inst = _instance(self.EVENT)
        _reg(inst, paid_at=self.PAID)
        gone = _reg(inst, paid_at=self.PAID)
        gone.status = 'cancelled'
        db.session.flush()
        gone.cancelled_at = datetime(2026, 9, 3, tzinfo=timezone.utc)
        db.session.flush()

        groups = [g for g in build_report(SEPT, now=NOW).revenue_groups
                  if g.title == inst.effective_title]

        assert sorted(g.withdrawn for g in groups) == [False, True]


def test_totals_add_up(app):
    paid = datetime(2026, 9, 5, tzinfo=timezone.utc)
    _reg(_instance(datetime(2026, 9, 12, tzinfo=timezone.utc)), paid, amount=1000)
    _reg(_instance(datetime(2026, 10, 17, tzinfo=timezone.utc)), paid, amount=1500)

    report = build_report(SEPT, now=NOW)

    assert report.revenue_total == sum(r.amount for r in report.revenue)
    assert report.liabilities_total == sum(r.amount for r in report.liabilities)
    assert report.revenue_total == report.revenue_events_total + report.revenue_online_total
