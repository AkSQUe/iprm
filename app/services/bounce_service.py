"""Опитування поштової скриньки (IMAP) на bounce/DSN -> suppression-список.

Працює лише якщо EmailSettings.bounce_polling_enabled = True (за замовчуванням
вимкнено). IMAP-логін -- ті самі креди, що й SMTP (та сама скринька courses@),
хост -- smtp_server, порт 993/SSL.

Парсимо стандартні DSN (multipart/report; delivery-status): беремо адреси з
Final-Recipient, де Action: failed -- це hard-bounce, додаємо у suppression,
щоб більше не слати (інакше репутація відправника падає). Оброблені листи
позначаємо \\Seen.
"""
import imaplib
import logging
import re
from email import message_from_bytes

from app.extensions import db
from app.models.email_settings import EmailSettings
from app.models.email_suppression import EmailSuppression

logger = logging.getLogger(__name__)

IMAP_PORT_SSL = 993
# Скільки повідомлень за один прохід (щоб не висіти довго).
_MAX_MESSAGES = 100
_FINAL_RCPT_RE = re.compile(r'Final-Recipient:\s*[^;]+;\s*([^\s]+)', re.IGNORECASE)
_ACTION_FAILED_RE = re.compile(r'Action:\s*failed', re.IGNORECASE)


def _extract_failed_recipients(raw_bytes):
    """Витягти адреси з Action: failed зі стандартного DSN. Повертає set."""
    failed = set()
    try:
        msg = message_from_bytes(raw_bytes)
    except Exception:
        return failed
    for part in msg.walk():
        if part.get_content_type() != 'message/delivery-status':
            continue
        text = part.as_string()
        # delivery-status -- набір per-recipient блоків, розділених порожнім
        # рядком; шукаємо ті, де є Action: failed.
        for block in re.split(r'\n\s*\n', text):
            if _ACTION_FAILED_RE.search(block):
                m = _FINAL_RCPT_RE.search(block)
                if m:
                    addr = m.group(1).strip().strip('<>').lower()
                    if '@' in addr:
                        failed.add(addr)
    return failed


def poll_bounces():
    """Один прохід полінгу. Повертає кількість доданих у suppression адрес.

    No-op, якщо bounce_polling_enabled вимкнено або немає IMAP-кредів.
    """
    settings = EmailSettings.get()
    if not settings.bounce_polling_enabled:
        return 0
    host = settings.smtp_server
    user = settings.smtp_username
    password = settings.smtp_password
    if not (host and user and password):
        logger.info('Bounce polling: SMTP/IMAP credentials incomplete, skipping')
        return 0

    added = 0
    try:
        conn = imaplib.IMAP4_SSL(host, IMAP_PORT_SSL)
        try:
            conn.login(user, password)
            conn.select('INBOX')
            # Невідкриті листи від mailer-daemon/postmaster.
            typ, data = conn.search(None, 'UNSEEN', 'FROM', 'MAILER-DAEMON')
            ids = data[0].split() if data and data[0] else []
            if not ids:
                typ, data = conn.search(None, 'UNSEEN', 'FROM', 'postmaster')
                ids = data[0].split() if data and data[0] else []
            for num in ids[:_MAX_MESSAGES]:
                typ, msg_data = conn.fetch(num, '(RFC822)')
                if typ != 'OK' or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                for addr in _extract_failed_recipients(raw):
                    _row, created = EmailSuppression.add(
                        addr, reason=EmailSuppression.REASON_BOUNCE,
                        source='imap_bounce', detail='Auto hard-bounce from DSN',
                    )
                    if created:
                        added += 1
                conn.store(num, '+FLAGS', '\\Seen')
            if added:
                db.session.commit()
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as exc:
        db.session.rollback()
        logger.warning('Bounce polling failed: %s', exc)
        return 0

    if added:
        logger.info('Bounce polling: %d addresses suppressed', added)
    return added
