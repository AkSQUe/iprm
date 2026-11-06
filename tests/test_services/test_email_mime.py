"""Технічна гігієна вихідного листа, яку бачать спам-фільтри.

Заголовки листа, що Microsoft поклав у «Небажану пошту» (06.11.2026), при
пройдених SPF/DKIM/DMARC показали три вади, які додавала сама відправка:

* Message-ID на внутрішнє ім'я сервера (`@vps-57566`) -- MID_RHS_NOT_FQDN;
* `multipart/mixed` без жодного вкладення -- CTYPE_MIXED_BOGUS;
* EHLO `[127.0.1.1]` у першому Received замість імені хоста.
"""
import email
from email import policy

from app.services import email_service
from app.services.email_service import OutgoingMessage


def _parsed(msg):
    return email.message_from_bytes(msg.as_bytes(), policy=policy.default)


def test_message_id_uses_sender_domain(app):
    with app.app_context():
        msg = OutgoingMessage(subject='S', recipients=['a@example.org'],
                              body='t', html='<p>t</p>',
                              sender=('ІПРМ', 'courses@iprm.space'))
        assert _parsed(msg)['Message-ID'].rstrip('>').endswith('@iprm.space')


def test_message_id_with_plain_string_sender(app):
    with app.app_context():
        msg = OutgoingMessage(subject='S', recipients=['a@example.org'],
                              body='t', sender='courses@iprm.space')
        assert _parsed(msg)['Message-ID'].rstrip('>').endswith('@iprm.space')


def test_no_attachments_is_plain_alternative(app):
    with app.app_context():
        msg = OutgoingMessage(subject='Тема', recipients=['a@example.org'],
                              body='текст', html='<p>текст</p>',
                              sender=('ІПРМ', 'courses@iprm.space'),
                              reply_to='courses@iprm.space',
                              extra_headers={'List-Unsubscribe': '<mailto:x@iprm.space>'})
        parsed = _parsed(msg)
    assert parsed.get_content_type() == 'multipart/alternative'
    assert [p.get_content_type() for p in parsed.iter_parts()] == [
        'text/plain', 'text/html']
    assert parsed['Subject'] == 'Тема'
    assert 'courses@iprm.space' in parsed['From']
    assert parsed['To'] == 'a@example.org'
    assert parsed['Reply-To'] == 'courses@iprm.space'
    assert parsed['List-Unsubscribe'] == '<mailto:x@iprm.space>'
    assert parsed['Date'] and parsed['Message-ID']
    top = msg.as_bytes().split(b'\r\n\r\n', 1)[0]
    names = [line.split(b':', 1)[0].lower() for line in top.split(b'\r\n')
             if line and not line[:1].isspace()]
    assert len(names) == len(set(names)), names


def test_with_attachment_stays_mixed(app):
    with app.app_context():
        msg = OutgoingMessage(subject='S', recipients=['a@example.org'],
                              body='t', html='<p>t</p>',
                              sender='courses@iprm.space')
        msg.attach('c.pdf', 'application/pdf', b'%PDF-1.4')
        parsed = _parsed(msg)
    assert parsed.get_content_type() == 'multipart/mixed'
    types = [p.get_content_type() for p in parsed.iter_parts()]
    assert types == ['multipart/alternative', 'application/pdf']


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, local_hostname=None):
        self.local_hostname = local_hostname
        _FakeSMTP.instances.append(self)

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def sendmail(self, *args):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_smtp_ehlo_names_sender_domain(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(email_service.smtplib, 'SMTP', _FakeSMTP)
    monkeypatch.setattr(email_service.smtplib, 'SMTP_SSL', _FakeSMTP)
    cfg = {'server': 's', 'port': 465, 'use_ssl': True, 'use_tls': False,
           'username': 'courses@iprm.space', 'password': 'x',
           'sender': ('ІПРМ', 'courses@iprm.space')}

    class _Msg:
        send_to = {'a@example.org'}

        def as_bytes(self):
            return b''

    email_service._smtp_send(_Msg(), cfg)
    email_service._open_smtp(cfg).ehlo()
    assert [s.local_hostname for s in _FakeSMTP.instances] == [
        'iprm.space', 'iprm.space']
