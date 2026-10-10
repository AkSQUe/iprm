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

Відмова учасника (погоджено 10.10.2026) -- статус «скасовано» або
задоволена заявка на повернення за Політикою (не різниця тарифу при
перенесенні):

* поки заявка учасника чекає рішення -- уся сума зобов'язання;
* повернення було -- утримане стає виручкою на дату повернення
  (refunded_at), а не заходу: закритий місяць після звірки вже не
  змінюється;
* повернення не було -- виручка на дату скасування (cancelled_at).

Дату виконання рахує ОДНА функція -- `fulfilled_at`. Її ж віддає API
партнеру (mm-medic): два звіти про ті самі гроші мусять сходитись, а
дві копії правила вже розійшлись одного разу.

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
from app.models.mixins import CANCELLED
from app.models.online_enrollment import OnlineEnrollment
from app.models.refund_request import (
    STATUS_APPROVED, STATUS_NEW, RefundRequest,
)
from app.models.registration import EventRegistration
from app.models.user import User
from app.utils import KYIV, ensure_utc

KIND_EVENT = 'event'
KIND_ONLINE = 'online'
KIND_LABELS = {KIND_EVENT: 'Захід', KIND_ONLINE: 'Онлайн-курс'}

#: Код заявки, що НЕ є відмовою учасника: різниця тарифу при перенесенні
#: (transfer_service). Решта кодів -- сітка Політики (refund_policy).
TRANSFER_DIFF = 'transfer_diff'


def _withdrawal_requests(requests):
    return [item for item in requests or () if item.quoted_code != TRANSFER_DIFF]


def fulfilled_at(order, requests=()):
    """Коли зобов'язання за оплаченим замовленням виконано (або буде).

    ``order`` -- EventRegistration чи OnlineEnrollment; ``requests`` -- його
    заявки на повернення (`refund_requests_for`). ``None`` -- не виконано і
    дати немає: заявка чекає рішення, у заходу немає дати, доступ не видано.

    Єдине місце правила: звіт виручки й API для mm-medic беруть дату
    звідси, тож розійтися не можуть. Правила -- у докстрінгу модуля.
    """
    withdrawal = _withdrawal_requests(requests)
    if any(item.status == STATUS_NEW for item in withdrawal):
        return None
    approved = [item.decided_at for item in withdrawal
                if item.status == STATUS_APPROVED and item.decided_at]
    if order.status == CANCELLED or approved:
        if order.refunded_total > 0 and order.refunded_at is not None:
            return order.refunded_at
        return order.cancelled_at or (max(approved) if approved else None)
    if hasattr(order, 'online_course_id'):
        return order.provisioned_at
    instance = order.instance
    return (instance.end_date or instance.start_date) if instance else None


def is_withdrawn(order, requests=()):
    """Відмова учасника: скасовано або заявку за Політикою задоволено."""
    return order.status == CANCELLED or any(
        item.status == STATUS_APPROVED for item in _withdrawal_requests(requests))


def refund_requests_for(registration_ids=(), enrollment_ids=()):
    """Заявки на повернення пачкою: {('reg'|'onl', id): [заявки]}."""
    clauses = []
    if registration_ids:
        clauses.append(RefundRequest.registration_id.in_(list(registration_ids)))
    if enrollment_ids:
        clauses.append(RefundRequest.enrollment_id.in_(list(enrollment_ids)))
    found = {}
    if not clauses:
        return found
    for item in RefundRequest.query.filter(or_(*clauses)):
        key = (('reg', item.registration_id) if item.registration_id is not None
               else ('onl', item.enrollment_id))
        found.setdefault(key, []).append(item)
    return found


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
    withdrawn: bool = False

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
    withdrawn: bool = False
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
                row.kind, row.title, row.fulfilled_at, row.withdrawn)
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


def _group_key(kind, owner_id, withdrawn, done):
    """Ключ групи. Відмови -- ще й за київським днем виконання: дата в
    них -- повернення чи скасування, своя в кожного, а група показує одну."""
    if not withdrawn:
        return (kind, owner_id, False, None)
    day = ensure_utc(done).astimezone(KYIV).date() if done else None
    return (kind, owner_id, True, day)


def _registration_row(reg, requests):
    """Рядок звіту. Відмови -- окремою групою: дата їхнього виконання --
    повернення чи скасування, а не заходу, і в одній групі з учасниками
    вона б губилась."""
    instance = reg.instance
    name, email = _person(reg.user)
    withdrawn = is_withdrawn(reg, requests)
    done = fulfilled_at(reg, requests)
    return FinanceRow(
        kind=KIND_EVENT,
        order_id=f'REG-{reg.id}',
        group_key=_group_key(KIND_EVENT, reg.instance_id, withdrawn, done),
        title=instance.effective_title if instance else '',
        fulfilled_at=done,
        participant=name, email=email,
        payment_method=reg.payment_method_label,
        paid_at=reg.paid_at, paid_at_precision=reg.paid_at_precision,
        payment_amount=_money(reg.payment_amount),
        refunded_amount=_money(reg.refunded_amount),
        withdrawn=withdrawn,
    )


def _enrollment_row(item, requests):
    name, email = _person(item.user)
    withdrawn = is_withdrawn(item, requests)
    done = fulfilled_at(item, requests)
    return FinanceRow(
        kind=KIND_ONLINE,
        order_id=item.order_id,
        group_key=_group_key(KIND_ONLINE, item.online_course_id, withdrawn, done),
        title=item.course.effective_title if item.course else '',
        fulfilled_at=done,
        participant=name, email=email,
        payment_method=dict(EventRegistration.PAYMENT_METHODS).get(
            item.payment_method, item.payment_method),
        paid_at=item.paid_at, paid_at_precision=item.paid_at_precision,
        payment_amount=_money(item.payment_amount),
        refunded_amount=_money(item.refunded_amount),
        withdrawn=withdrawn,
    )


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

    regs = (
        db.session.query(EventRegistration)
        .options(joinedload(EventRegistration.user).joinedload(User.medical_profile),
                 joinedload(EventRegistration.instance)
                 .joinedload(CourseInstance.course))
        .filter(*_paid(EventRegistration))
        .order_by(EventRegistration.id)
        .all()
    )
    online = (
        db.session.query(OnlineEnrollment)
        .options(joinedload(OnlineEnrollment.user).joinedload(User.medical_profile),
                 joinedload(OnlineEnrollment.course))
        .filter(*_paid(OnlineEnrollment))
        .order_by(OnlineEnrollment.id)
        .all()
    )
    # Дата виконання залежить від заявок на повернення, тож відбір -- у
    # Python за `fulfilled_at`, а не SQL-ом за датою заходу: правило одне на
    # звіт і API. Оплачених рядків сотні.
    requests = refund_requests_for([reg.id for reg in regs],
                                   [item.id for item in online])
    rows = ([_registration_row(reg, requests.get(('reg', reg.id), ()))
             for reg in regs]
            + [_enrollment_row(item, requests.get(('onl', item.id), ()))
               for item in online])

    far = datetime.max.replace(tzinfo=timezone.utc)

    def done(row):
        return ensure_utc(row.fulfilled_at)

    def order(row):
        return (done(row) or far, row.kind, row.order_id)

    report.revenue = sorted(
        (row for row in rows
         if done(row) is not None and start <= done(row) < as_of),
        key=order)
    # Зобов'язання на межу звіту: гроші вже прийшли, а виконання ще попереду
    # (або дати немає зовсім -- тоді воно не виконане, і це теж треба
    # бачити).
    report.liabilities = sorted(
        (row for row in rows
         if ensure_utc(row.paid_at) < as_of
         and (done(row) is None or done(row) >= as_of)),
        key=order)
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
