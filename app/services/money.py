"""Форматування грошових сум для шаблонів.

Шаблони друкували суму через `| int`, і це мовчки округлювало вниз: після
промокоду на 5999.40 грн від тарифу 6000 грн до сплати лишалось 0.60, а в
листі стояло "0 UAH". Людина бачила нуль і вважала, що платіж зламався
(REG-4299/4300, 06.08.2026).

Правило: копійки показуємо ТІЛЬКИ якщо вони є. 6000.00 -> "6000",
0.60 -> "0.60". Цілі суми (переважна більшість) виглядають як раніше, а
дробові перестають зникати.
"""
from decimal import Decimal, InvalidOperation


CURRENCY = 'UAH'


# Нерозривний пробіл: "20 000" не має шансу переламатись між рядками так,
# щоб "20" лишилось наприкінці одного, а "000" поїхало на наступний.
GROUP_SEP = ' '


def _group_thousands(digits):
    """'20000' -> '20 000'. Розряди по три, справа наліво."""
    parts = []
    while len(digits) > 3:
        parts.append(digits[-3:])
        digits = digits[:-3]
    parts.append(digits)
    return GROUP_SEP.join(reversed(parts))


def format_amount(value):
    """Сума без валюти: '6 000', '0.60'. Порожнє значення -> ''.

    Розряди розділені нерозривним пробілом: «20000 ₴» читається як набір
    цифр, який доводиться рахувати очима, а «20 000 ₴» -- як сума. Це
    український стандарт запису й водночас те, як число виглядає в будь-якій
    виписці, з якою адмін звіряє цифри.
    """
    if value is None or value == '':
        return ''
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    amount = amount.quantize(Decimal('0.01'))
    sign = '-' if amount < 0 else ''
    amount = abs(amount)
    if amount == amount.to_integral_value():
        return sign + _group_thousands(str(int(amount)))
    # normalize прибрав би значущий нуль у "0.60" -> "0.6"; формат фіксований.
    whole, _, cents = f'{amount:.2f}'.partition('.')
    return f'{sign}{_group_thousands(whole)}.{cents}'


def money(value, currency=CURRENCY):
    """Сума з валютою: '6000 UAH', '0.60 UAH'. Порожнє значення -> ''."""
    text = format_amount(value)
    if not text:
        return ''
    return f'{text} {currency}' if currency else text
