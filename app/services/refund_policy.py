"""Політика повернення коштів у виконуваному вигляді.

Джерело правди -- опублікована Політика (`templates/main/refund.html`).
Тут вона перекладена в код рівно тому, що адмін інакше рахує відсоток
подумки: помилка в такому розрахунку -- це або недоплата учаснику, або
повернення грошей, які ми за політикою мали утримати.

Модуль чистий: жодного звернення до БД і жодних побічних ефектів. На вхід
-- об'єкт реєстрації/замовлення, на вихід -- рекомендована сума. Рішення
за адміном: `quote_*` нічого не проводить і нічого не забороняє, окрім
випадку `refundable=False` (цифровий продукт після видачі доступу), який
перевіряє вже `payment_ops`.

Сума з `quote_*` -- це стеля ЗА ПОЛІТИКОЮ від повної вартості замовлення.
Обмеження за фактичним залишком (якщо частину вже повернули) робить
`payment_ops`: тільки він знає `refunded_amount`.
"""
from collections import namedtuple
from decimal import Decimal, ROUND_HALF_UP

from app.models.mixins import utcnow
from app.utils import ensure_utc

RefundQuote = namedtuple(
    'RefundQuote',
    'percent amount code label refundable note days',
)

# Політика §4.1. Пороги свідомо розписані умовами, а не таблицею з
# порогами: "більше ніж за 7 днів" і "від 3 до 7 днів" мають різну
# строгість нерівності, і будь-яка спроба звести це в один цикл робить
# межу 7 днів неоднозначною.
TIER_LABELS = {
    'early': 'Більше ніж за 7 днів до заходу',
    'standard': 'Від 3 до 7 днів до заходу',
    'late': 'Менше ніж за 3 дні до заходу',
    'no_show': 'Захід уже розпочався (неявка без попередньої відмови)',
    'no_event_date': 'Дата заходу невідома',
    'digital_open': 'Цифровий продукт, доступ ще не надано',
    'digital_provisioned': 'Цифровий продукт, доступ уже надано',
}


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def tier_for_days(days):
    """Код тарифної сходинки за кількістю днів до початку заходу.

    `days` -- дробове число (0.5 -- дванадцять годин), бо політика оперує
    строком подання заявки, а не календарними датами.
    """
    if days is None:
        return 'no_event_date'
    if days > 7:
        return 'early'
    if days >= 3:
        return 'standard'
    if days > 0:
        return 'late'
    return 'no_show'


TIER_PERCENT = {
    'early': 100,
    'standard': 50,
    'late': 25,
    'no_show': 0,
    # Дату заходу порахувати не вдалося -- пропонуємо повну суму, але
    # позначаємо кодом, щоб адмін глянув очима. Занизити автоматично тут
    # гірше: людина отримає менше, ніж їй належить, і не дізнається чому.
    'no_event_date': 100,
    'digital_open': 100,
    'digital_provisioned': 0,
}


def days_until(start_date, requested_at=None):
    """Скільки днів лишилось до початку заходу на момент заявки."""
    if start_date is None:
        return None
    now = ensure_utc(requested_at) if requested_at else utcnow()
    delta = ensure_utc(start_date) - now
    return delta.total_seconds() / 86400.0


def _quote(code, base_amount, days=None, note=None, refundable=True):
    percent = TIER_PERCENT[code]
    return RefundQuote(
        percent=percent,
        amount=_money(Decimal(str(base_amount or 0)) * percent / 100),
        code=code,
        label=TIER_LABELS[code],
        refundable=refundable,
        note=note,
        days=days,
    )


def quote_registration(reg, requested_at=None):
    """Рекомендована сума повернення за реєстрацію на захід (§4.1).

    `requested_at` -- дата подання заявки учасником (§4.2), а не дата
    натискання кнопки адміном. Заявка могла пролежати в пошті три дні, і
    відсоток мусить рахуватись від дати листа.
    """
    instance = getattr(reg, 'instance', None)
    start = getattr(instance, 'start_date', None) if instance else None
    days = days_until(start, requested_at)
    code = tier_for_days(days)

    note = None
    if code == 'no_event_date':
        note = ('У проведення не вказана дата початку -- сходинку політики '
                'обчислити не можна, перевірте суму вручну.')
    elif code == 'no_show':
        note = ('Захід уже розпочався. За політикою §4.3 повернення за '
                'неявку без попередньої відмови не здійснюється.')

    return _quote(code, reg.payment_amount, days=days, note=note)


def quote_enrollment(enrollment, requested_at=None):
    """Рекомендована сума повернення за онлайн-курс (§5).

    Дата тут ні до чого: цифровий продукт ділиться рівно на два випадки --
    доступ ще не відкривали (§5.4, повне повернення) або вже відкрили
    (§5.1--5.3, повернення не здійснюється).
    """
    provisioned = getattr(enrollment, 'provisioned_at', None) is not None
    if provisioned:
        return _quote(
            'digital_provisioned', enrollment.payment_amount,
            refundable=False,
            note=('Доступ до матеріалів уже надано. За політикою §5.1 '
                  'повернення коштів за цифровий продукт після надання '
                  'доступу не здійснюється.'),
        )
    return _quote('digital_open', enrollment.payment_amount)


def quote_for(order, requested_at=None):
    """Диспетчер за типом замовлення -- зручно для адмін-шаблонів."""
    if hasattr(order, 'online_course_id'):
        return quote_enrollment(order, requested_at)
    return quote_registration(order, requested_at)
