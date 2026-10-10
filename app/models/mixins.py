from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import event, inspect

from app.extensions import db
from app.i18n import DEFAULT_LANGUAGE, PREFIXED_LANGUAGES, apply_json_overrides


def utcnow():
    return datetime.now(timezone.utc)


# BigInteger для PostgreSQL, Integer для SQLite (autoincrement)
BigIntPK = db.BigInteger().with_variant(db.Integer, 'sqlite')


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SoftDeleteMixin:
    """М'яке видалення: рядок лишається в БД з відміткою deleted_at.

    Потрібне для undo: адмін видаляє одним кліком, без діалогу, і має вікно,
    щоб натиснути "Повернути" у тості. Рядки остаточно чистить фонова задача
    purge_soft_deleted (app.services.scheduler_service).

    Запити мусять явно відсікати видалене -- alive() або
    filter(Model.deleted_at.is_(None)). Автоматичного фільтра свідомо немає:
    неявна поведінка запитів ховала б від читача, які саме рядки він бачить.
    """
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def soft_delete(self):
        self.deleted_at = utcnow()

    def restore(self):
        self.deleted_at = None

    @classmethod
    def alive(cls):
        """Запит лише за невидаленими рядками."""
        return cls.query.filter(cls.deleted_at.is_(None))


class DiscountedMixin:
    """Знижка на замовленні -- спільна для реєстрації та онлайн-курсу.

    Ключове правило, заради якого це винесено: `payment_amount` ЗАВЖДИ
    містить суму ПІСЛЯ знижки, а `discount_amount` -- лише знімок того,
    скільки ми віддали. Все, що рахує гроші далі (повернення в тому числі),
    працює з payment_amount і нічого віднімати вдруге не мусить.

    Обидва типи замовлень мали однакові колонки, але властивості були лише
    в реєстрації: шаблон, спільний для обох, мовчки не показував би знижку
    на курсах.
    """

    @property
    def has_discount(self):
        return bool(self.discount_amount and self.discount_amount > 0)

    @property
    def amount_before_discount(self):
        """Сума до знижки (payment_amount уже містить суму після неї)."""
        if not self.has_discount:
            return self.payment_amount
        return (self.payment_amount or 0) + self.discount_amount


# Точність дати оплати. 'datetime' -- момент відомий (LiqPay, ручна позначка
# "зараз"); 'date' -- відомий лише день (дата з виписки, записана полуднем за
# Києвом). Без неї споживач (MM Medic, XLSX) показує вигаданий полудень як
# справжній час платежу.
PAID_AT_DATETIME = 'datetime'
PAID_AT_DATE = 'date'
PAID_AT_PRECISIONS = (PAID_AT_DATETIME, PAID_AT_DATE)


def paid_at_precision_check(name):
    """CHECK: точність заповнена тоді й лише тоді, коли заповнена дата.

    `IS NOT NULL` перед `IN` -- не зайвий: `NULL IN (...)` дає NULL, а
    CHECK відкидає рядок лише на FALSE. Без нього дата без точності
    проходила б.
    """
    return db.CheckConstraint(paid_at_precision_sql(), name=name)


def paid_at_precision_sql():
    """Умова CHECK-а точності -- спільна для моделі й міграції."""
    allowed = ', '.join(f"'{value}'" for value in PAID_AT_PRECISIONS)
    return (
        '(paid_at IS NULL AND paid_at_precision IS NULL) OR '
        '(paid_at IS NOT NULL AND paid_at_precision IS NOT NULL '
        f'AND paid_at_precision IN ({allowed}))'
    )


class PaidAtMixin:
    """Дата оплати замовлення разом із її точністю.

    Пишеться лише парою -- set_paid_at / clear_paid_at: дата без точності
    відкидається CHECK-ом (paid_at_precision_check), і пряме присвоєння
    paid_at впало б на першому ж flush.
    """
    paid_at = db.Column(db.DateTime(timezone=True))
    paid_at_precision = db.Column(db.String(8))

    def set_paid_at(self, moment, precision):
        if precision not in PAID_AT_PRECISIONS:
            raise ValueError(f'Невідома точність дати оплати: {precision!r}')
        self.paid_at = moment
        self.paid_at_precision = precision

    def clear_paid_at(self):
        self.paid_at = None
        self.paid_at_precision = None


#: Статус скасованого замовлення -- однаковий у реєстрації й онлайн-курсу.
CANCELLED = 'cancelled'


class CancellableMixin:
    """Коли замовлення скасовано -- момент, а не лише статус.

    Потрібен фінзвіту (app.services.finance_report): оплата, від якої
    учасник відмовився без повернення, стає виручкою саме на дату
    скасування (рішення власника 10.10.2026). Статус цього моменту не
    зберігав, а `updated_at` зсувається з будь-якою наступною правкою.

    Ставиться слухачами нижче на КОЖНУ зміну статусу -- адмінкою, повним
    поверненням (payment_ops), імпортом: шлях, який забув би це зробити
    сам, тут неможливий. Повернення зі скасованого стану дату знімає.
    """
    cancelled_at = db.Column(db.DateTime(timezone=True))


@event.listens_for(CancellableMixin, 'before_insert', propagate=True)
def _cancelled_on_insert(mapper, connection, target):
    if target.status == CANCELLED and target.cancelled_at is None:
        target.cancelled_at = utcnow()


@event.listens_for(CancellableMixin, 'before_update', propagate=True)
def _cancelled_on_update(mapper, connection, target):
    history = inspect(target).attrs.status.history
    if not history.has_changes():
        return
    if target.status != CANCELLED:
        target.cancelled_at = None
    elif CANCELLED not in (history.deleted or ()):
        target.cancelled_at = utcnow()


class RefundableMixin:
    """Повернення коштів за замовлення (реєстрація на захід чи онлайн-курс).

    Спільний міксин, а не по копії колонок у кожній моделі: розбіжність між
    двома типами замовлень тут означала б, що за один з них можна повернути
    більше, ніж заплачено.

    `refunded_amount` накопичувальна -- політика (§4.1) допускає повернення
    частини, а рішень про повернення за одне замовлення може бути кілька.
    NOT NULL DEFAULT 0, щоб жодна перевірка залишку не порівнювала None із
    сумою. `payment_status` стає 'refunded' ЛИШЕ коли повернено все:
    часткове повернення лишає замовлення оплаченим і діючим.
    """
    refunded_amount = db.Column(
        db.Numeric(10, 2), default=0, server_default='0', nullable=False,
    )
    refunded_at = db.Column(db.DateTime(timezone=True))
    refund_reason = db.Column(db.String(500))

    @property
    def refunded_total(self):
        return Decimal(str(self.refunded_amount or 0))

    @property
    def refund_remaining(self):
        """Скільки ще можна повернути за цим замовленням."""
        paid = Decimal(str(self.payment_amount or 0))
        return max(Decimal('0'), paid - self.refunded_total)

    @property
    def side_payments_received(self):
        """Скільки надійшло ОКРЕМИМИ платежами поза цим order_id.

        Базово нуль: у звичайного замовлення все зайшло одним платежем.
        Перевизначає лише EventRegistration -- доплата різниці тарифу при
        перенесенні йде окремим замовленням SUR-<transfer_id>.
        """
        return Decimal('0')

    @property
    def refund_available(self):
        """Стеля повернення ПРОТИ ВЛАСНОГО order_id замовлення.

        LiqPay уміє повернути лише те, що прийшло на конкретне замовлення.
        `payment_amount` же несе суму всіх платежів разом, тож просити за
        REG- більше, ніж на нього надійшло, -- це відмова LiqPay, після
        якої адмін не може повернути навіть первісну суму: правильного
        числа він нізвідки не знає.

        Різницю, що лишилась поза цією стелею, повертають вручну в
        кабінеті LiqPay -- див. docs/registration-transfer.md.
        """
        return max(Decimal('0'),
                   self.refund_remaining - self.side_payments_received)

    @property
    def has_refund(self):
        return self.refunded_total > 0

    @property
    def is_fully_refunded(self):
        paid = Decimal(str(self.payment_amount or 0))
        return paid > 0 and self.refunded_total >= paid

    @property
    def is_partially_refunded(self):
        return self.has_refund and not self.is_fully_refunded


def _current_language():
    try:
        from flask_babel import get_locale
        return str(get_locale() or DEFAULT_LANGUAGE)
    except Exception:
        # Поза app-контекстом (скрипти, частина фонових задач) -- дефолт.
        return DEFAULT_LANGUAGE


class TranslatableMixin:
    """Переклади контентних полів моделі (ru/en; українська -- канонічні
    колонки, тому окремого бакета "uk" немає).

    translations -- JSON {"ru": {<поле>: <значення>, ...}, "en": {...}}.
    Рядкові поля зберігають переклад рядком; JSON-поля (faq, регалії, блоки
    блогу) -- як ПЛОСКУ мапу overrides {шлях: текст}, що накладається на
    поточну українську структуру при читанні (app.i18n.apply_json_overrides).
    Перелік перекладних полів модель оголошує у __translatable__.

    Читання: obj.t('title') -- значення активної локалі з фолбеком на
    українську (відсутні/порожні переклади не показують діри в UI; для
    JSON-полів зміни оригіналу підхоплюються автоматично, застарілі
    переклади-шляхи ігноруються).
    Запис: set_translation(...) -- присвоює НОВИЙ dict, щоб SQLAlchemy
    зафіксував зміну JSON-колонки без MutableDict.
    """
    __translatable__ = ()

    translations = db.Column(db.JSON)

    def t(self, field, lang=None):
        if lang is None:
            lang = _current_language()
        uk_value = getattr(self, field)
        if lang == DEFAULT_LANGUAGE or field not in self.__translatable__:
            return uk_value
        stored = ((self.translations or {}).get(lang) or {}).get(field)
        if stored in (None, '', [], {}):
            return uk_value
        # JSON-структура -> overrides {шлях: текст}; рядок -> прямий переклад.
        if isinstance(uk_value, (list, dict)):
            return apply_json_overrides(uk_value, stored)
        return stored

    def set_translation(self, lang, field, value):
        if lang not in PREFIXED_LANGUAGES:
            raise ValueError(f'lang має бути одною з {PREFIXED_LANGUAGES}')
        if field not in self.__translatable__:
            raise ValueError(
                f'{field} не входить у __translatable__ {type(self).__name__}'
            )
        data = {k: dict(v or {}) for k, v in (self.translations or {}).items()}
        bucket = data.setdefault(lang, {})
        if value in (None, '', [], {}):
            bucket.pop(field, None)
        else:
            bucket[field] = value
        self.translations = data
