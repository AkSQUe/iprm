"""Число прописом українською (для суми у рахунку на оплату).

number_to_words_ua(1523.45) -> "одна тисяча п'ятсот двадцять три гривні 45 копійок"
"""
from decimal import Decimal


def number_to_words_ua(amount, currency='UAH'):
    if isinstance(amount, str):
        amount = Decimal(amount)
    integer_part = int(amount)
    decimal_part = int(round((abs(amount) - abs(integer_part)) * 100))
    words = _int_to_words_ua(integer_part)
    currency_word = _currency_name(integer_part, currency)
    kopiyky_word = _kopiyky_name(decimal_part)
    return f'{words} {currency_word} {decimal_part:02d} {kopiyky_word}'


def _int_to_words_ua(n):
    if n == 0:
        return 'нуль'
    if n < 0:
        return 'мінус ' + _int_to_words_ua(-n)

    ones = ['', 'один', 'два', 'три', 'чотири', "п'ять", 'шість', 'сім', 'вісім', "дев'ять"]
    ones_f = ['', 'одна', 'дві', 'три', 'чотири', "п'ять", 'шість', 'сім', 'вісім', "дев'ять"]
    tens = ['', '', 'двадцять', 'тридцять', 'сорок', "п'ятдесят", 'шістдесят', 'сімдесят', 'вісімдесят', "дев'яносто"]
    teens = ['десять', 'одинадцять', 'дванадцять', 'тринадцять', 'чотирнадцять',
             "п'ятнадцять", 'шістнадцять', 'сімнадцять', 'вісімнадцять', "дев'ятнадцять"]
    hundreds = ['', 'сто', 'двісті', 'триста', 'чотириста', "п'ятсот", 'шістсот', 'сімсот', 'вісімсот', "дев'ятсот"]

    def _under_1000(num, feminine=False):
        if num == 0:
            return ''
        result = []
        h = num // 100
        if h > 0:
            result.append(hundreds[h])
        remainder = num % 100
        if 10 <= remainder < 20:
            result.append(teens[remainder - 10])
        else:
            t = remainder // 10
            if t > 0:
                result.append(tens[t])
            o = remainder % 10
            if o > 0:
                result.append(ones_f[o] if feminine else ones[o])
        return ' '.join(result)

    millions = n // 1000000
    thousands = (n % 1000000) // 1000
    units = n % 1000
    result = []
    if millions > 0:
        result.append(_under_1000(millions))
        result.append(_million_name(millions))
    if thousands > 0:
        result.append(_under_1000(thousands, feminine=True))
        result.append(_thousand_name(thousands))
    if units > 0:
        result.append(_under_1000(units))
    return ' '.join(p for p in result if p)


def _plural_ua(n, one, few, many):
    if n % 100 in (11, 12, 13, 14):
        return many
    d = n % 10
    if d == 1:
        return one
    if d in (2, 3, 4):
        return few
    return many


def _million_name(n):
    return _plural_ua(n, 'мільйон', 'мільйони', 'мільйонів')


def _thousand_name(n):
    return _plural_ua(n, 'тисяча', 'тисячі', 'тисяч')


def _currency_name(n, currency='UAH'):
    if currency.upper() == 'UAH':
        return _plural_ua(n, 'гривня', 'гривні', 'гривень')
    if currency.upper() == 'USD':
        return _plural_ua(n, 'долар', 'долари', 'доларів')
    if currency.upper() == 'EUR':
        return 'євро'
    return 'грн.'


def _kopiyky_name(n):
    return _plural_ua(n, 'копійка', 'копійки', 'копійок')
