"""Unit tests for the MM Medic materials integration (IPRM side).

Covers the XLSX template round-trip and the outgoing client's request signing,
which must match what the MM Medic partner API verifies:
    HMAC-SHA256(secret, "<timestamp>.<raw_body>")
Neither needs a database.
"""
import hashlib
import hmac
import tempfile
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.services import xlsx_io
from app.services.mm_medic_client import MMMedicClient, _sign, MMConfigError


# ----------------------------- XLSX round-trip -----------------------------

def test_export_then_parse_ignores_blank_and_zero_rows():
    catalog = [
        {'sku': 'AAA-1', 'name': 'Голка', 'available': 50, 'image': 'https://x/y.jpg', 'is_consumable': True},
        {'sku': 'BBB-2', 'name': 'Пробірка', 'available': 12, 'image': None, 'is_consumable': True},
        {'sku': 'CCC-3', 'name': 'Марля', 'available': 5, 'image': None, 'is_consumable': False},
    ]
    bio = xlsx_io.export_materials_template_xlsx(catalog)
    tmp = Path(tempfile.gettempdir()) / 'iprm_materials_unit.xlsx'
    tmp.write_bytes(bio.getvalue())
    try:
        wb = load_workbook(tmp)
        ws = wb.active
        # header order: sku, name, image, available, quantity -> quantity col = 5
        ws.cell(row=2, column=5, value=10)   # AAA-1 -> 10
        ws.cell(row=3, column=5, value=0)    # BBB-2 -> 0 (ignored)
        # CCC-3 left blank (ignored)
        wb.save(tmp)

        parsed = xlsx_io.parse_materials_xlsx(tmp)
        assert parsed == {'AAA-1': 10}
    finally:
        tmp.unlink(missing_ok=True)


def test_export_empty_catalog_produces_valid_workbook():
    bio = xlsx_io.export_materials_template_xlsx([])
    tmp = Path(tempfile.gettempdir()) / 'iprm_materials_empty.xlsx'
    tmp.write_bytes(bio.getvalue())
    try:
        assert xlsx_io.parse_materials_xlsx(tmp) == {}
    finally:
        tmp.unlink(missing_ok=True)


# ----------------------------- client signing -----------------------------

def test_sign_matches_hmac_of_timestamp_dot_body():
    ts, body, secret = '1700000000', b'{"a":1}', 'shared'
    expected = hmac.new(secret.encode(), ts.encode() + b'.' + body, hashlib.sha256).hexdigest()
    assert _sign(ts, body, secret) == expected


def test_sign_empty_body_is_defined_for_get():
    ts, secret = '1700000000', 'shared'
    expected = hmac.new(secret.encode(), ts.encode() + b'.', hashlib.sha256).hexdigest()
    assert _sign(ts, b'', secret) == expected


def test_from_settings_requires_enabled_flag():
    class S:
        mm_medic_integration_enabled = False
        mm_medic_api_base_url = 'https://mm-medic.com'
        partner_webhook_secret = 'x'
    with pytest.raises(MMConfigError):
        MMMedicClient.from_settings(S())


def test_from_settings_requires_url_and_secret():
    class S:
        mm_medic_integration_enabled = True
        mm_medic_api_base_url = ''
        partner_webhook_secret = ''
    with pytest.raises(MMConfigError):
        MMMedicClient.from_settings(S())
