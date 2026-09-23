"""Вкладення листа переживають автоповтор і кнопку «переслати».

Лист із рахунком, календарним запрошенням чи сертифікатом збирається з байтів
у пам'яті. Раніше і `retry_failed_emails`, і `manual_resend` збирали його
заново лише з `html_body` -- тож після тимчасового збою SMTP людина
отримувала «файл у вкладенні» без файлу. Тепер байти зберігаються в
`email_attachments` доти, доки лист може знадобитися відправити знову.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.email_attachment import EmailAttachment
from app.models.email_log import EmailLog
from app.services import email_service
from app.services.email_service import EmailService

PDF = b'%PDF-1.4 test attachment bytes'
SMTP_CFG = {
    'server': 'smtp.example.com', 'port': 587, 'use_ssl': False, 'use_tls': True,
    'username': 'u@example.com', 'password': 'x', 'is_enabled': True,
    'has_password': True, 'sender': 'u@example.com',
}


@pytest.fixture
def enabled_mail(monkeypatch):
    """Увімкнена пошта без мережі; сам потік відправки не запускаємо."""
    monkeypatch.setattr(email_service, '_get_smtp_config', lambda app: SMTP_CFG)
    monkeypatch.setattr(EmailService, '_send_in_thread', staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(EmailService, '_check_circuit_breaker', staticmethod(lambda: False))


@pytest.fixture
def mail_enabled_in_settings(app):
    from app.models.email_settings import EmailSettings
    settings = EmailSettings.get()
    previous = settings.is_enabled
    settings.is_enabled = True
    db.session.flush()
    yield settings
    settings.is_enabled = previous


def _failed_log_with_attachment(created_at=None, data=PDF, error='Connection reset'):
    log = EmailLog(
        to_email='tc-attach@test.com', subject='Ваш рахунок',
        template_name='registration_confirmed', status='failed',
        error_message=error, trigger='payment', html_body='<p>Рахунок у вкладенні</p>',
    )
    if created_at is not None:
        log.created_at = created_at
    db.session.add(log)
    db.session.flush()
    db.session.add(EmailAttachment(email_log_id=log.id, filename='invoice.pdf',
                                   mimetype='application/pdf', data=data))
    db.session.commit()
    return log


def test_send_email_stores_attachments_with_the_log(app, enabled_mail):
    log = EmailService.send_email(
        to='tc-attach-store@test.com', subject='Сертифікат',
        template_name='certificate_issued',
        context={'user': None, 'certificate': _fake_certificate(), 'account_url': '/'},
        trigger='certificate', idempotency_key='test-attach-store',
        attachments=[('cert.pdf', 'application/pdf', PDF)],
    )
    assert log is not None and log.status == 'pending'
    stored = EmailAttachment.query.filter_by(email_log_id=log.id).all()
    assert [(a.filename, a.mimetype, a.data) for a in stored] == [
        ('cert.pdf', 'application/pdf', PDF)]


def test_successful_send_purges_bytes_but_keeps_marker(app):
    """Після успіху байти не потрібні -- але рядок лишається маркером."""
    log = _failed_log_with_attachment()
    log.status = 'pending'
    db.session.commit()
    msg = email_service.Message(subject='x', recipients=[log.to_email], html='<p>x</p>')
    with patch.object(email_service, '_smtp_send'):
        EmailService._send_in_thread(app, msg, log.id, SMTP_CFG)
    db.session.expire_all()
    stored = EmailAttachment.query.filter_by(email_log_id=log.id).one()
    assert db.session.get(EmailLog, log.id).status == 'sent'
    assert stored.data is None
    assert stored.filename == 'invoice.pdf'


def test_retry_resends_with_the_original_attachment(app, mail_enabled_in_settings):
    log = _failed_log_with_attachment()
    sent_messages = []

    def fake_send_many(messages, cfg):
        sent_messages.extend(messages)
        return [(m, None) for m in messages]

    with patch.object(email_service, '_get_smtp_config', lambda app: SMTP_CFG), \
            patch.object(EmailService, '_check_circuit_breaker', staticmethod(lambda: False)), \
            patch.object(email_service, '_smtp_send_many', side_effect=fake_send_many):
        retried = EmailService.retry_failed_emails()
    assert retried == 1
    (msg,) = [m for m in sent_messages if m.recipients == [log.to_email]]
    assert [(a.filename, a.content_type, a.data) for a in msg.attachments] == [
        ('invoice.pdf', 'application/pdf', PDF)]
    db.session.expire_all()
    assert db.session.get(EmailLog, log.id).status == 'sent'
    assert EmailAttachment.query.filter_by(email_log_id=log.id).one().data is None


def test_retry_never_sends_a_letter_whose_attachment_is_gone(app, mail_enabled_in_settings):
    """Байти вже стерто -- лист без файлу гірший за невідправлений."""
    log = _failed_log_with_attachment(data=None)
    sent_messages = []
    with patch.object(email_service, '_get_smtp_config', lambda app: SMTP_CFG), \
            patch.object(EmailService, '_check_circuit_breaker', staticmethod(lambda: False)), \
            patch.object(email_service, '_smtp_send_many',
                         side_effect=lambda ms, cfg: sent_messages.extend(ms) or
                         [(m, None) for m in ms]):
        EmailService.retry_failed_emails()
    assert not [m for m in sent_messages if m.recipients == [log.to_email]]
    db.session.expire_all()
    assert db.session.get(EmailLog, log.id).status == 'failed'


def test_manual_resend_includes_the_attachment(app, mail_enabled_in_settings):
    log = _failed_log_with_attachment()
    captured = []
    with patch.object(email_service, '_get_smtp_config', lambda app: SMTP_CFG), \
            patch.object(email_service, '_smtp_send',
                         side_effect=lambda msg, cfg: captured.append(msg)):
        ok, _message = EmailService.manual_resend(log.id)
    assert ok
    assert [(a.filename, a.data) for a in captured[0].attachments] == [('invoice.pdf', PDF)]
    db.session.expire_all()
    assert EmailAttachment.query.filter_by(email_log_id=log.id).one().data is None


def test_manual_resend_refuses_when_attachment_is_gone(app, mail_enabled_in_settings):
    log = _failed_log_with_attachment(data=None)
    with patch.object(email_service, '_get_smtp_config', lambda app: SMTP_CFG), \
            patch.object(email_service, '_smtp_send') as smtp:
        ok, message = EmailService.manual_resend(log.id)
    assert not ok
    assert 'вкладення' in message.lower()
    assert not smtp.called


def test_purge_keeps_recent_failures_and_clears_old_ones(app):
    now = datetime.now(timezone.utc)
    recent = _failed_log_with_attachment(created_at=now - timedelta(days=1))
    old = _failed_log_with_attachment(
        created_at=now - timedelta(days=email_service.ATTACHMENT_FAILED_RETENTION_DAYS + 1))
    purged = EmailService.purge_stale_attachments()
    assert purged >= 1
    db.session.expire_all()
    assert EmailAttachment.query.filter_by(email_log_id=recent.id).one().data == PDF
    assert EmailAttachment.query.filter_by(email_log_id=old.id).one().data is None


def test_purge_clears_bytes_of_sent_letters(app):
    log = _failed_log_with_attachment()
    log.status = 'sent'
    db.session.commit()
    EmailService.purge_stale_attachments()
    db.session.expire_all()
    assert EmailAttachment.query.filter_by(email_log_id=log.id).one().data is None


def _fake_certificate():
    from types import SimpleNamespace
    return SimpleNamespace(event_title='Захід', number='N-1', event_date=None,
                           cpd_points=None, specialties=None)
