"""Виручка й зобов'язання за місяць: що ми вже відпрацювали, а що винні.

Оплата -- ще не виручка. Гроші за захід, який відбудеться наступного
місяця, -- наше зобов'язання перед учасником (кредиторка): до заходу він
має право на повернення за Політикою. Виручкою вони стають, коли
зобов'язання виконано.

Правила (погоджено 08.10.2026):

* Захід -- виконано, щойно він відбувся: настала дата завершення
  (end_date, а без неї -- start_date). Присутність учасника не важлива:
  після заходу повернення за Політикою вже немає.
* Онлайн-курс -- виконано, щойно видано доступ (provisioned_at): це
  цифровий продукт, повернення після видачі немає.
* Виручка належить місяцю виконання, а не місяцю оплати. Оплата з вересня
  за захід 17.10 -- зобов'язання на кінець вересня й виручка жовтня.
* Сума -- сплачене мінус уже повернене (часткові повернення). Повністю
  повернені замовлення (payment_status='refunded') не рахуються.
* Оплата без дати (paid_at порожній) у звіт не йде, а показується окремо:
  без дати її не віднести ні до виручки, ні до зобов'язань на кінець
  місяця.

Межі місяця -- київські: о 00:30 1-го числа за Києвом UTC-дата ще
попередня, і оплата лягла б не в той місяць.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.online_enrollment import OnlineEnrollment
from app.models.registration import EventRegistration
from app.models.user import User
from app.utils import KYIV, ensure_utc

KIND_EVENT = 'event'
KIND_ONLINE = 'online'
KIND_LABELS = {KIND_EVENT: 'Захід', KIND_ONLINE: 'Онлайн-курс'}


@dataclass
class FinanceRow:
    """Одне замовлення у звіті: реєстрація на захід чи покупка курсу."""
    kind: str
    order_id: str
    group_key: tuple
    title: str
    fulfilled_at: datetime  # коли виконано (або буде); None -- дата не відома
    participant: str
    email: str
    payment_method: str
    paid_at: datetime
    paid_at_precision: str
    payment_amount: Decimal
    refunded_amount: Decimal

    @property
    def amount(self):
        """Сума, що лишається в нас: сплачене мінус повернене."""
        return self.payment_amount - self.refunded_amount

    @property
    def kind_label(self):
        return KIND_LABELS[self.kind]


@dataclass
class FinanceGroup:
    """Підсумок за одним заходом чи курсом."""
    kind: str
    title: str
    fulfilled_at: datetime
    count: int = 0
    amount: Decimal = Decimal('0')

    @property
    def kind_label(self):
        return KIND_LABELS[self.kind]


@dataclass
class FinanceReport:
    month: date
    as_of: datetime  # межа звіту: кінець місяця або "зараз" для поточного
    revenue: list = field(default_factory=list)
    liabilities: list = field(default_factory=list)
    undated: list = field(default_factory=list)  # id оплачених без дати

    @property
    def is_current(self):
        return self.as_of < month_bounds(self.month)[1]

    @property
    def revenue_total(self):
        return _total(self.revenue)

    @property
    def revenue_events_total(self):
        return _total(r for r in self.revenue if r.kind == KIND_EVENT)

    @property
    def revenue_online_total(self):
        return _total(r for r in self.revenue if r.kind == KIND_ONLINE)

    @property
    def liabilities_total(self):
        return _total(self.liabilities)

    @property
    def revenue_groups(self):
        return _groups(self.revenue)

    @property
    def liability_groups(self):
        return _groups(self.liabilities)


def _total(rows):
    return sum((row.amount for row in rows), Decimal('0'))


def _groups(rows):
    groups = OrderedDict()
    for row in rows:
        group = groups.get(row.group_key)
        if group is None:
            group = groups[row.group_key] = FinanceGroup(
                row.kind, row.title, row.fulfilled_at)
        group.count += 1
        group.amount += row.amount
    far = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(groups.values(),
                  key=lambda g: (ensure_utc(g.fulfilled_at) or far, g.title))


def month_bounds(month):
    """[початок місяця, початок наступного) за Києвом, в UTC."""
    start = datetime(month.year, month.month, 1, tzinfo=KYIV)
    nxt = datetime(month.year + month.month // 12, month.month % 12 + 1, 1,
                   tzinfo=KYIV)
    return start.astimezone(timezone.utc), nxt.astimezone(timezone.utc)


def parse_month(value, today=None):
    """'YYYY-MM' -> перше число місяця; порожнє чи сміття -- поточний місяць."""
    try:
        parsed = datetime.strptime((value or '').strip(), '%Y-%m')
        return date(parsed.year, parsed.month, 1)
    except ValueError:
        today = today or datetime.now(KYIV).date()
        return today.replace(day=1)


def _money(value):
    return Decimal(str(value or 0))


def _person(user):
    if user is None:
        return '', ''
    return (user.full_name or '').strip(), user.email or ''


def _registration_rows(query):
    rows = []
    for reg in query:
        instance = reg.instance
        name, email = _person(reg.user)
        rows.append(FinanceRow(
            kind=KIND_EVENT,
            order_id=f'REG-{reg.id}',
            group_key=(KIND_EVENT, reg.instance_id),
            title=instance.effective_title if instance else '',
            fulfilled_at=(instance.end_date or instance.start_date) if instance else None,
            participant=name, email=email,
            payment_method=reg.payment_method_label,
            paid_at=reg.paid_at, paid_at_precision=reg.paid_at_precision,
            payment_amount=_money(reg.payment_amount),
            refunded_amount=_money(reg.refunded_amount),
        ))
    return rows


def _enrollment_rows(query):
    rows = []
    for item in query:
        name, email = _person(item.user)
        rows.append(FinanceRow(
            kind=KIND_ONLINE,
            order_id=item.order_id,
            group_key=(KIND_ONLINE, item.online_course_id),
            title=item.course.effective_title if item.course else '',
            fulfilled_at=item.provisioned_at,
            participant=name, email=email,
            payment_method=dict(EventRegistration.PAYMENT_METHODS).get(
                item.payment_method, item.payment_method),
            paid_at=item.paid_at, paid_at_precision=item.paid_at_precision,
            payment_amount=_money(item.payment_amount),
            refunded_amount=_money(item.refunded_amount),
        ))
    return rows


def _paid(model):
    """Оплачене, з датою і з ненульовим залишком після повернень."""
    return (
        model.payment_status == 'paid',
        model.paid_at.isnot(None),
        model.payment_amount - func.coalesce(model.refunded_amount, 0) > 0,
    )


def build_report(month, now=None):
    """Звіт за київський місяць `month` (date, перше число)."""
    start, end = month_bounds(month)
    now = now or datetime.now(timezone.utc)
    as_of = min(end, now)
    report = FinanceReport(month=month, as_of=as_of)

    event_end = func.coalesce(CourseInstance.end_date, CourseInstance.start_date)
    regs = (
        db.session.query(EventRegistration)
        .join(CourseInstance, CourseInstance.id == EventRegistration.instance_id)
        .options(joinedload(EventRegistration.user).joinedload(User.medical_profile),
                 joinedload(EventRegistration.instance)
                 .joinedload(CourseInstance.course))
        .filter(*_paid(EventRegistration))
    )
    online = (
        db.session.query(OnlineEnrollment)
        .options(joinedload(OnlineEnrollment.user).joinedload(User.medical_profile),
                 joinedload(OnlineEnrollment.course))
        .filter(*_paid(OnlineEnrollment))
    )

    report.revenue = (
        _registration_rows(regs.filter(event_end >= start, event_end < as_of)
                           .order_by(event_end, EventRegistration.id))
        + _enrollment_rows(online.filter(OnlineEnrollment.provisioned_at >= start,
                                         OnlineEnrollment.provisioned_at < as_of)
                           .order_by(OnlineEnrollment.provisioned_at,
                                     OnlineEnrollment.id))
    )
    # Зобов'язання на межу звіту: гроші вже прийшли, а виконання ще попереду
    # (або дати заходу немає зовсім -- тоді воно не виконане ніколи, і це
    # теж треба бачити).
    report.liabilities = (
        _registration_rows(regs.filter(EventRegistration.paid_at < as_of,
                                       or_(event_end.is_(None), event_end >= as_of))
                           .order_by(event_end, EventRegistration.id))
        + _enrollment_rows(online.filter(OnlineEnrollment.paid_at < as_of,
                                         or_(OnlineEnrollment.provisioned_at.is_(None),
                                             OnlineEnrollment.provisioned_at >= as_of))
                           .order_by(OnlineEnrollment.id))
    )
    report.undated = [
        f'REG-{reg_id}' for (reg_id,) in db.session.query(EventRegistration.id).filter(
            EventRegistration.payment_status == 'paid',
            EventRegistration.paid_at.is_(None),
            EventRegistration.payment_amount > 0,
        ).order_by(EventRegistration.id)
    ] + [
        f'ONL-{item_id}' for (item_id,) in db.session.query(OnlineEnrollment.id).filter(
            OnlineEnrollment.payment_status == 'paid',
            OnlineEnrollment.paid_at.is_(None),
            OnlineEnrollment.payment_amount > 0,
        ).order_by(OnlineEnrollment.id)
    ]
    return report
