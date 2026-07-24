"""Локалізація листів: вибір мови отримувача + рендер під force_locale."""
from flask_babel import force_locale
from flask import render_template

from app.services.email_service import EmailService, DEFAULT_EMAIL_LOCALE


class _User:
    def __init__(self, lang):
        self.preferred_language = lang


def test_recipient_locale_explicit_lang_wins():
    assert EmailService._recipient_locale({'user': _User('ru')}, lang='en') == 'en'


def test_recipient_locale_from_user_preference():
    assert EmailService._recipient_locale({'user': _User('ru')}) == 'ru'


def test_recipient_locale_defaults_uk():
    assert EmailService._recipient_locale({'user': _User(None)}) == DEFAULT_EMAIL_LOCALE
    assert EmailService._recipient_locale({}) == DEFAULT_EMAIL_LOCALE
    assert EmailService._recipient_locale(None) == DEFAULT_EMAIL_LOCALE


def test_email_renders_under_force_locale(app):
    with app.test_request_context('/'):
        with force_locale('en'):
            html = render_template('emails/password_reset.html',
                                   user=None, reset_url='https://x/reset')
        assert 'password' in html.lower() or 'reset' in html.lower()


def test_email_uk_canonical(app):
    with app.test_request_context('/'):
        with force_locale('uk'):
            html = render_template('emails/password_reset.html',
                                   user=None, reset_url='https://x/reset')
        assert 'парол' in html.lower()
