"""Спільний Fernet-хелпер: той самий ключ, що й у SiteSettings/EmailSettings."""
from app.crypto import decrypt_str, encrypt_str, encrypted_field, get_fernet


class _Holder:
    _secret = ''
    secret = encrypted_field('_secret')


def test_roundtrip():
    token = encrypt_str('UA123')
    assert token and token != 'UA123'
    assert decrypt_str(token) == 'UA123'


def test_empty_is_empty():
    assert encrypt_str('') == ''
    assert encrypt_str(None) == ''
    assert decrypt_str('') == ''


def test_broken_token_gives_empty():
    assert decrypt_str('not-a-token') == ''


def test_descriptor_strips_and_encrypts():
    h = _Holder()
    h.secret = '  1234567890  '
    assert h._secret != '1234567890'
    assert h.secret == '1234567890'
    h.secret = ''
    assert h._secret == ''


def test_same_key_as_site_settings():
    from app.models.site_settings import SiteSettings
    s = SiteSettings.get()
    s.partner_api_key = 'k-1'
    assert get_fernet().decrypt(s._partner_api_key_encrypted.encode()).decode() == 'k-1'
