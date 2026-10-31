"""Призначення платежу в рахунку: номер REG-/ONL- + ПІБ учасника."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.payment_purpose import build_payment_purpose, order_ref


def _user(first, last):
    return SimpleNamespace(full_name=' '.join(p for p in (last, first) if p))


def _reg(user, created):
    return SimpleNamespace(id=1234, user=user, created_at=created)


def _enrollment(user, created):
    return SimpleNamespace(
        id=56, online_course_id=7, order_id='ONL-56', user=user, created_at=created,
    )


# 31.10.2026 12:00 UTC = 14:00 за Києвом
NOON = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def test_purpose_registration():
    reg = _reg(SimpleNamespace(full_name='Береза Олена Іванівна'), NOON)
    assert build_payment_purpose(reg) == (
        'Оплата згідно рахунку № REG-1234 від 31.10.2026 за Береза Олена Іванівна'
    )


def test_purpose_without_name_has_no_suffix():
    reg = _reg(_user('', ''), NOON)
    assert build_payment_purpose(reg) == 'Оплата згідно рахунку № REG-1234 від 31.10.2026'


def test_purpose_without_user_has_no_suffix():
    assert build_payment_purpose(_reg(None, NOON)).endswith('від 31.10.2026')


def test_purpose_enrollment_uses_order_id():
    purpose = build_payment_purpose(_enrollment(_user('Олена', 'Береза'), NOON))
    assert purpose == 'Оплата згідно рахунку № ONL-56 від 31.10.2026 за Береза Олена'


def test_purpose_date_is_kyiv_not_utc():
    late = datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc)  # 31.10 00:30 Київ
    assert 'від 31.10.2026' in build_payment_purpose(_reg(_user('О', 'Б'), late))


def test_order_ref():
    assert order_ref(_reg(None, NOON)) == 'REG-1234'
    assert order_ref(_enrollment(None, NOON)) == 'ONL-56'


def test_invoice_header_date_matches_purpose_in_kyiv_time():
    """30.10 22:30 UTC = 31.10 00:30 за Києвом: шапка й призначення -- 31 жовтня."""
    from app.services.invoice_service import _date_phrase
    late = datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc)
    assert _date_phrase(late) == '31 жовтня 2026 р.'
    assert build_payment_purpose(_reg(None, late)).endswith('від 31.10.2026')
