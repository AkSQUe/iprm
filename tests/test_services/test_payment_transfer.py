"""Реквізити переказу: ті самі призначення й QR, що в рахунку.

Номер REG-/ONL- у призначенні -- контракт із mm-medic: за ним переказ
зіставляється з реєстрацією одразу. Тому сторінки й лист беруть призначення
з того самого build_payment_purpose, що й PDF, а QR -- з тих самих даних.
"""
import base64
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.site_settings import SiteSettings
from app.services.payment_purpose import (
    build_payment_purpose, build_surcharge_purpose,
)
from app.services.payment_transfer import (
    TransferDetails, qr_png_bytes, transfer_details,
)

NOON = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
GOOD_IBAN = 'UA' + '2' * 27


@pytest.fixture
def requisites(app):
    settings = SiteSettings.get()
    before = (settings.company_full_name, settings.bank_iban,
              settings.edrpou, settings.bank_name)
    settings.company_full_name = 'ТОВ ІПРМ'
    settings.bank_iban = GOOD_IBAN
    settings.edrpou = '12345678'
    settings.bank_name = 'АТ Банк'
    yield settings
    (settings.company_full_name, settings.bank_iban,
     settings.edrpou, settings.bank_name) = before


def _reg(amount=Decimal('1500')):
    user = SimpleNamespace(full_name='Береза Олена')
    return SimpleNamespace(id=4313, user=user, created_at=NOON,
                           payment_amount=amount)


def _decode_qr_payload(payload):
    body = payload.rsplit('/', 1)[1]
    raw = base64.urlsafe_b64decode(body + '=' * (-len(body) % 4))
    lines = raw.decode('cp1251' if raw.split(b'\n')[2] == b'2' else 'utf-8')
    return lines.split('\n')


def test_details_repeat_invoice_requisites_and_purpose(requisites):
    reg = _reg()
    details = transfer_details(reg)

    assert details.recipient == 'ТОВ ІПРМ'
    assert details.edrpou == '12345678'
    assert details.bank == 'АТ Банк'
    assert details.iban == GOOD_IBAN
    assert details.amount == Decimal('1500')
    assert details.purpose == build_payment_purpose(reg)
    assert 'REG-4313' in details.purpose


def test_qr_carries_amount_and_purpose_with_number(requisites):
    details = transfer_details(_reg())
    lines = _decode_qr_payload(details.qr_payload)

    assert lines[6] == GOOD_IBAN
    assert lines[7] == 'UAH1500'
    assert 'REG-4313' in lines[11]
    assert details.qr_svg_data_uri.startswith('data:image/svg+xml')


def test_png_is_png(requisites):
    png = transfer_details(_reg()).qr_png()
    assert png[:8] == b'\x89PNG\r\n\x1a\n'


def test_bad_iban_drops_qr_but_keeps_text(requisites):
    """Те саме правило, що в рахунку: текст лишається, QR -- ні."""
    requisites.bank_iban = 'UA12'
    details = transfer_details(_reg())

    assert details.qr_payload is None
    assert details.qr_svg_data_uri is None
    assert details.qr_png() is None
    assert details.iban == 'UA12'
    assert 'REG-4313' in details.purpose


def test_explicit_amount_and_purpose_win(requisites):
    """Доплата різниці тарифу: сума й призначення не з замовлення."""
    details = transfer_details(_reg(), amount=Decimal('500'),
                               purpose='Доплата різниці тарифу SUR-7')
    lines = _decode_qr_payload(details.qr_payload)

    assert details.amount == Decimal('500')
    assert lines[7] == 'UAH500'
    assert lines[11] == 'Доплата різниці тарифу SUR-7'


def test_surcharge_purpose_names_sur_number_and_payer():
    """SUR-<id перенесення> -- для mm-medic «не зіставляти автоматично»."""
    transfer = SimpleNamespace(
        id=7, registration=SimpleNamespace(user=SimpleNamespace(full_name='Береза Олена')))
    assert build_surcharge_purpose(transfer) == (
        'Доплата різниці тарифу SUR-7 за Береза Олена')


def test_surcharge_purpose_without_name():
    transfer = SimpleNamespace(id=7, registration=SimpleNamespace(user=None))
    assert build_surcharge_purpose(transfer) == 'Доплата різниці тарифу SUR-7'


def test_qr_png_bytes_direct():
    assert qr_png_bytes('https://bank.gov.ua/qr/QkNE')[:4] == b'\x89PNG'


def test_details_is_immutable(requisites):
    details = transfer_details(_reg())
    assert isinstance(details, TransferDetails)
    with pytest.raises(Exception):
        details.purpose = 'інше'
