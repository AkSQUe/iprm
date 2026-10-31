"""Платіжний QR-код рахунку -- стандарт НБУ, версія формату 002.

Перенесено з сайту mm-medic (app/services/documents/payment_qr.py), щоб
рахунки обох сайтів сканувались однаково.

Банківські застосунки читають не сирий текст, а URL виду

    https://bank.gov.ua/qr/<Base64URL(структура даних)>

КРИТИЧНО для сумісності: споживчий Приват24 розпізнає лише легасі-формат
v002 зі СТАРИМ хостом bank.gov.ua/qr/ (v003 з qr.bank.gov.ua він відхиляє;
monobank/Raiffeisen/Приват24 Бізнес читають обидві версії). Тому генеруємо
v002, у якому отримувач обмежений 38 символами, а призначення -- 140.

Структура v002 -- 13 рядків, роздільник LF:

     1 BCD            -- службова мітка
     2 002            -- версія
     3 <кодування>    -- 2 = Win-1251 (як в еталоні НБУ), 1 = UTF-8
     4 UCT            -- функція (у v002 лише кредитовий переказ)
     5 (порожньо)     -- зарезервовано
     6 <отримувач>    -- до 38 символів
     7 <IBAN>         -- UA + 27 цифр
     8 UAH<сума>      -- хвостові нулі обрізаються: UAH1500, UAH1540.5
     9 <код>          -- ЄДРПОУ (8) або РНОКПП (10)
    10 (порожньо)
    11 (порожньо)
    12 <призначення>  -- до 140 символів
    13 (порожньо)

Некоректні IBAN, код отримувача чи сума -- ValueError (fail closed): краще
рахунок без QR, ніж QR, який банк відхилить або заповнить неправильно.
"""
import base64
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Union

NBU_QR_BASE_URL_V002 = 'https://bank.gov.ua/qr/'

MAX_RECIPIENT_NAME_V002 = 38
MAX_PURPOSE_V002 = 140
MAX_URL_SIZE = 507
MAX_AMOUNT = Decimal('999999999.99')

FUNCTION_UCT = 'UCT'

_UA_IBAN_RE = re.compile(r'^UA\d{27}$')
_RECIPIENT_CODE_RE = re.compile(r'^\d{8}(\d{2})?$')

Amount = Union[Decimal, float, int, str, None]


def _clean(value: Optional[str]) -> str:
    """Схлопнути пробіли й переноси: LF усередині поля зламав би структуру."""
    return ' '.join((value or '').split())


def _format_amount(amount: Amount) -> str:
    """`UAH` + сума без хвостових нулів (UAH1500, UAH1540.5)."""
    if amount is None:
        return ''
    try:
        value = Decimal(str(amount)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP,
        )
    except Exception as exc:
        raise ValueError(f'invalid amount {amount!r}') from exc
    if value <= 0:
        raise ValueError(f'amount must be positive, got {amount!r}')
    if value > MAX_AMOUNT:
        raise ValueError(f'amount exceeds NBU limit {MAX_AMOUNT}: {amount!r}')
    return 'UAH' + f'{value:.2f}'.rstrip('0').rstrip('.')


def _pick_v002_encoding(*fields: str) -> str:
    """'2' (Win-1251, як в еталоні НБУ), а якщо текст у ньому не вміщається --
    '1' (UTF-8)."""
    try:
        for field in fields:
            field.encode('cp1251')
        return '2'
    except UnicodeEncodeError:
        return '1'


def build_nbu_qr_data_v002(
    recipient_name: str,
    iban: str,
    recipient_code: str,
    purpose: str,
    amount: Amount = None,
) -> str:
    """Зібрати 13-рядкову структуру даних QR v002 (до Base64URL)."""
    name = _clean(recipient_name)
    if not name:
        raise ValueError('recipient_name is required for payment QR')

    iban_norm = (iban or '').replace(' ', '').upper()
    if not _UA_IBAN_RE.match(iban_norm):
        raise ValueError(f'IBAN must match UA + 27 digits, got {iban!r}')

    code = re.sub(r'\D', '', recipient_code or '')
    if not _RECIPIENT_CODE_RE.match(code):
        raise ValueError(
            'recipient_code must be 8-digit EDRPOU or 10-digit RNOKPP, '
            f'got {recipient_code!r}'
        )

    purpose_norm = _clean(purpose)
    if not purpose_norm:
        raise ValueError('purpose is required for payment QR')

    lines = [
        'BCD',
        '002',
        _pick_v002_encoding(name, purpose_norm),
        FUNCTION_UCT,
        '',
        name[:MAX_RECIPIENT_NAME_V002],
        iban_norm,
        _format_amount(amount),
        code,
        '',
        '',
        purpose_norm[:MAX_PURPOSE_V002],
        '',
    ]
    return '\n'.join(lines)


def build_nbu_qr_url(qr_data: str) -> str:
    """Обгорнути структуру в платіжний URL: Base64URL без '='.

    Байти кодуються за прапорцем у рядку 3: 2 = Win-1251, 1 = UTF-8.
    """
    lines = qr_data.split('\n')
    codec = 'cp1251' if len(lines) > 2 and lines[2] == '2' else 'utf-8'
    encoded = base64.urlsafe_b64encode(qr_data.encode(codec)).decode('ascii')
    url = NBU_QR_BASE_URL_V002 + encoded.rstrip('=')
    if len(url) > MAX_URL_SIZE:
        raise ValueError(f'QR URL too long: {len(url)} > {MAX_URL_SIZE}')
    return url


def build_nbu_qr_payload(
    recipient_name: str,
    iban: str,
    amount: Amount,
    purpose: str,
    recipient_code: str,
) -> str:
    """Повний платіжний URL для QR-коду рахунку."""
    data = build_nbu_qr_data_v002(
        recipient_name=recipient_name,
        iban=iban,
        recipient_code=recipient_code,
        purpose=purpose,
        amount=amount,
    )
    return build_nbu_qr_url(data)


def qr_svg_data_uri(payload: str) -> str:
    """SVG data-URI QR-коду для `<img src>` в HTML, який рендерить WeasyPrint.

    ECC рівень M; micro=False (банківські сканери Micro QR не зобов'язані
    читати); border=4 -- специфікаційна тиха зона; light='#fff' -- явний
    білий фон, інакше SVG прозорий і тиха зона фарбується фоном сторінки.
    """
    import segno

    qr = segno.make(payload, error='m', micro=False)
    return qr.svg_data_uri(border=4, light='#fff', scale=4, nl=False)
