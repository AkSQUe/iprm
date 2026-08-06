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


def format_amount(value):
    """Сума без валюти: '6000', '0.60'. Порожнє значення -> ''."""
    if value is None or value == '':
        return ''
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    amount = amount.quantize(Decimal('0.01'))
    if amount == amount.to_integral_value():
        return str(int(amount))
    # normalize прибрав би значущий нуль у "0.60" -> "0.6"; формат фіксований.
    return f'{amount:.2f}'


def money(value, currency=CURRENCY):
    """Сума з валютою: '6000 UAH', '0.60 UAH'. Порожнє значення -> ''."""
    text = format_amount(value)
    if not text:
        return ''
    return f'{text} {currency}' if currency else text
