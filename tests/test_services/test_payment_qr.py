"""Платіжний QR НБУ v002: ліміти полів, кодування, fail closed."""
import base64

import pytest

from app.services.payment_qr import (
    build_nbu_qr_payload, qr_svg_data_uri,
)

IBAN = 'UA213052990000026003006239637'
HOST = 'https://bank.gov.ua/qr/'


def decode(url):
    assert url.startswith(HOST)
    body = url[len(HOST):]
    raw = base64.urlsafe_b64decode(body + '=' * (-len(body) % 4))
    lines = raw.decode('cp1251').split('\n')
    return lines


def test_qr_payload_respects_v002_limits():
    url = build_nbu_qr_payload(
        recipient_name='Т' * 60, iban=IBAN, amount='1500.00',
        purpose='Оплата згідно рахунку № REG-1 за ' + 'Б' * 120,
        recipient_code='45871060',
    )
    lines = decode(url)
    assert len(lines) == 13
    assert lines[:4] == ['BCD', '002', '2', 'UCT']
    assert len(lines[5]) <= 38
    assert lines[6] == IBAN
    assert lines[7] == 'UAH1500'
    assert lines[8] == '45871060'
    assert len(lines[11]) <= 140
    assert lines[11].startswith('Оплата згідно рахунку № REG-1')


def test_qr_amount_keeps_kopecks():
    url = build_nbu_qr_payload('ТОВ', IBAN, '1540.50', 'x', '45871060')
    assert decode(url)[7] == 'UAH1540.5'


@pytest.mark.parametrize('iban,code,amount', [
    ('UA12', '45871060', '10'),
    (IBAN, '123', '10'),
    (IBAN, '45871060', '0'),
])
def test_qr_fails_closed(iban, code, amount):
    with pytest.raises(ValueError):
        build_nbu_qr_payload('ТОВ', iban, amount, 'x', code)


def test_svg_data_uri():
    uri = qr_svg_data_uri(build_nbu_qr_payload('ТОВ', IBAN, '10', 'x', '45871060'))
    assert uri.startswith('data:image/svg+xml')
