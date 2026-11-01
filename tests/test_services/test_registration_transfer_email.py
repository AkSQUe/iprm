"""Лист «Реєстрацію підтверджено»: призначення з REG- і QR -- у самому листі.

Людина, що платить переказом із телефона, читає саме лист. Поки
призначення з номером REG-<id> жило лише в PDF-вкладенні, його
переписували як бачили, і mm-medic лишався без номера, за яким переказ
зіставляється з реєстрацією одразу.

QR -- вбудоване зображення (CID-вкладення), а не посилання на сервер і не
data:-URI: перше пошта блокує як зовнішню картинку, друге частина клієнтів
не показує зовсім. PNG, а не SVG: SVG у листі Gmail не малює.
"""
import re
from datetime import timedelta
from decimal import Decimal
from email import message_from_bytes
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.email_attachment import EmailAttachment
from app.models.email_log import EmailLog
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import email_service
from app.services.email_service import EmailService, _html_to_plaintext
from app.services.payment_purpose import build_payment_purpose

PDF = b'%PDF-1.4 fake'
SMTP_CFG = {
    'server': 'smtp.example.com', 'port': 587, 'use_ssl': False,
    'use_tls': True, 'username': 'u@example.com', 'password': 'x',
    'is_enabled': True, 'has_password': True, 'sender': 'u@example.com',
}


@pytest.fixture
def sent(monkeypatch):
    """Увімкнена пошта без мережі: перехоплюємо зібране повідомлення."""
    messages = []
    monkeypatch.setattr(email_service, '_get_smtp_config',
                        lambda app: SMTP_CFG)
    monkeypatch.setattr(
        EmailService, '_send_in_thread',
        staticmethod(lambda app, msg, log_id, cfg: messages.append(msg)))
    monkeypatch.setattr(EmailService, '_check_circuit_breaker',
                        staticmethod(lambda: False))
    monkeypatch.setattr(EmailService, 'notify_admins_event',
                        staticmethod(lambda **kw: None))
    return messages


@pytest.fixture
def settings(app):
    item = SiteSettings.get()
    before = (item.pay_invoice_enabled, item.bank_iban)
    yield item
    item.pay_invoice_enabled, item.bank_iban = before
    db.session.flush()


@pytest.fixture
def registration(app):
    uid = uuid4().hex[:6]
    user = User.create_with_password(
        f'rte-{uid}@test.com', 'password123',
        first_name='Олена', last_name='Береза', email_confirmed=True,
    )
    course = Course(title='Курс', slug=f'rte-{uid}', is_active=False)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='published', price=1000,
        start_date=utcnow() + timedelta(days=30),
    )
    db.session.add(instance)
    db.session.flush()
    item = EventRegistration(
        user_id=user.id, instance_id=instance.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status='pending', payment_status='unpaid',
        payment_amount=Decimal('1000'), payment_method='invoice',
    )
    db.session.add(item)
    db.session.flush()
    return item


def _log():
    return EmailLog.query.filter_by(
        template_name='registration_confirmed').order_by(
        EmailLog.id.desc()).first()


def _cid(html):
    found = re.search(r'src="cid:([^"]+)"', html)
    return found.group(1) if found else None


def _send(registration):
    with patch('app.services.invoice_service.render_invoice_pdf',
               return_value=PDF):
        return EmailService.send_registration_confirmation(registration)


class TestUnpaid:
    def test_html_has_purpose_and_inline_qr(self, registration, sent,
                                            mail_enabled):
        log = _send(registration)

        purpose = build_payment_purpose(registration)
        assert f'REG-{registration.id}' in purpose
        assert purpose in log.html_body
        cid = _cid(log.html_body)
        assert cid, 'QR мав стояти в листі вбудованим зображенням'
        assert 'data:image' not in log.html_body
        assert 'bank.gov.ua/qr' not in log.html_body

    def test_message_carries_inline_png_with_matching_cid(
            self, registration, sent, mail_enabled):
        log = _send(registration)
        cid = _cid(log.html_body)

        raw = sent[-1].as_bytes()
        parsed = message_from_bytes(raw)
        inline = [p for p in parsed.walk()
                  if p.get('Content-ID') == f'<{cid}>']
        assert len(inline) == 1
        part = inline[0]
        assert part.get_content_type() == 'image/png'
        assert part.get_content_disposition() == 'inline'
        assert part.get_payload(decode=True)[:4] == b'\x89PNG'

    def test_invoice_pdf_still_attached(self, registration, sent,
                                        mail_enabled):
        _send(registration)

        parsed = message_from_bytes(sent[-1].as_bytes())
        types = [p.get_content_type() for p in parsed.walk()]
        assert 'application/pdf' in types
        assert 'image/png' in types

    def test_plain_text_part_has_purpose(self, registration, sent,
                                         mail_enabled):
        log = _send(registration)
        assert build_payment_purpose(registration) in _html_to_plaintext(
            log.html_body)
        assert build_payment_purpose(registration) in sent[-1].body

    def test_qr_stored_with_content_id_for_retry(self, registration, sent,
                                                 mail_enabled):
        """Автоповтор і «переслати» збирають лист зі збереженого: без
        content_id QR поїхав би звичайним вкладенням, а картинка в листі --
        порожньою рамкою."""
        log = _send(registration)
        cid = _cid(log.html_body)

        stored = EmailAttachment.query.filter_by(email_log_id=log.id).all()
        qr = [a for a in stored if a.content_id == cid]
        assert len(qr) == 1 and qr[0].mimetype == 'image/png'

    def test_liqpay_choice_still_gets_transfer_block(self, registration, sent,
                                                     mail_enabled):
        """Переказ можливий, поки спосіб увімкнено, -- обраний LiqPay його
        не скасовує (сторінка так само показує обидва способи)."""
        registration.payment_method = 'liqpay'
        db.session.flush()

        log = _send(registration)

        assert build_payment_purpose(registration) in log.html_body
        assert _cid(log.html_body)


class TestNoTransfer:
    def test_paid_has_no_block_and_no_qr(self, registration, sent,
                                         mail_enabled):
        registration.payment_status = 'paid'
        db.session.flush()

        log = _send(registration)

        assert f'REG-{registration.id}' not in log.html_body
        assert _cid(log.html_body) is None
        parsed = message_from_bytes(sent[-1].as_bytes())
        assert 'image/png' not in [p.get_content_type() for p in parsed.walk()]

    def test_invoice_method_off_has_no_block(self, registration, sent,
                                             mail_enabled, settings):
        settings.pay_invoice_enabled = False
        db.session.flush()

        log = _send(registration)

        assert f'REG-{registration.id}' not in log.html_body
        assert _cid(log.html_body) is None

    def test_bad_iban_keeps_text_drops_qr(self, registration, sent,
                                          mail_enabled, settings):
        settings.bank_iban = 'UA12'
        db.session.flush()

        log = _send(registration)

        assert build_payment_purpose(registration) in log.html_body
        assert _cid(log.html_body) is None


def test_resend_keeps_qr_inline(app, registration, sent, mail_enabled,
                                monkeypatch):
    log = _send(registration)
    cid = _cid(log.html_body)
    sent_now = []
    monkeypatch.setattr(email_service, '_smtp_send',
                        lambda msg, cfg: sent_now.append(msg))

    ok, _message = EmailService.manual_resend(log.id)

    assert ok
    parsed = message_from_bytes(sent_now[-1].as_bytes())
    inline = [p for p in parsed.walk() if p.get('Content-ID') == f'<{cid}>']
    assert len(inline) == 1
    assert inline[0].get_content_disposition() == 'inline'


@pytest.fixture
def mail_enabled(app):
    from app.models.email_settings import EmailSettings
    item = EmailSettings.get()
    previous = item.is_enabled
    item.is_enabled = True
    db.session.flush()
    yield item
    item.is_enabled = previous
