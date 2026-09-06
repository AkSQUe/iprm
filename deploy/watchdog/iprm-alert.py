#!/var/www/iprm/venv/bin/python3
"""Mail an infrastructure alert to the site admins.

Usage:  echo "body text" | iprm-alert.py "subject suffix"

Deliberately standalone. It reads the SMTP settings straight out of the database
and never calls create_app(), because create_app() calls init_scheduler(), which
starts APScheduler and rewrites job rows in the shared production database --
unacceptable in a short-lived process that may fire every few minutes.

Only two things are borrowed from the application: the .env file (DATABASE_URL,
SECRET_KEY) and the Fernet key derivation used for the stored SMTP password,
which must stay in sync with app/models/email_settings.py::_get_fernet.
"""
import base64
import hashlib
import smtplib
import socket
import sys
from email.message import EmailMessage

ENV_PATH = '/var/www/iprm/.env'
OVERRIDE_PATH = '/etc/iprm-watchdog.conf'


def read_kv(path, required=False):
    """Parse a trivial KEY=value file; returns {} when absent and not required."""
    values = {}
    try:
        handle = open(path, encoding='utf-8')
    except FileNotFoundError:
        if required:
            raise
        return values
    with handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main():
    subject_suffix = sys.argv[1] if len(sys.argv) > 1 else 'alert'
    body = sys.stdin.read()

    env = read_kv(ENV_PATH, required=True)
    database_url = env.get('DATABASE_URL')
    secret_key = env.get('SECRET_KEY')
    if not database_url or not secret_key:
        sys.stderr.write('DATABASE_URL or SECRET_KEY missing from .env\n')
        return 1

    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    with engine.connect() as conn:
        row = conn.execute(text(
            'SELECT smtp_server, smtp_port, smtp_use_ssl, smtp_use_tls, '
            '       smtp_username, smtp_password, default_sender, sender_name '
            'FROM email_settings WHERE id = 1'
        )).first()
        if row is None:
            sys.stderr.write('no email_settings row\n')
            return 1
        # Override wins when set, so alerts can be redirected without a code change.
        recipients = [
            addr.strip() for addr in
            read_kv(OVERRIDE_PATH).get('ALERT_TO', '').split(',')
            if addr.strip()
        ]
        if not recipients:
            recipients = [r[0] for r in conn.execute(text(
                'SELECT DISTINCT u.email FROM users u '
                'JOIN user_roles ur ON ur.user_id = u.id '
                'JOIN roles r ON r.id = ur.role_id '
                "WHERE u.is_active IS TRUE AND u.email IS NOT NULL AND u.email <> '' "
                "  AND (r.name = 'super_admin' OR EXISTS ("
                '    SELECT 1 FROM role_permissions rp '
                '    JOIN permissions p ON p.id = rp.permission_id '
                "    WHERE rp.role_id = r.id AND p.name = 'notifications.receive'"
                '  ))'
            ))]

    if not recipients:
        sys.stderr.write('no admin recipients found\n')
        return 1
    if not row.smtp_server:
        sys.stderr.write('SMTP server not configured\n')
        return 1

    password = ''
    if row.smtp_password:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
        password = Fernet(key).decrypt(row.smtp_password.encode()).decode()

    sender = row.default_sender or row.smtp_username
    message = EmailMessage()
    message['Subject'] = '[IPRM %s] %s' % (socket.gethostname(), subject_suffix)
    message['From'] = '%s <%s>' % (row.sender_name or 'IPRM', sender)
    message['To'] = ', '.join(recipients)
    message['Auto-Submitted'] = 'auto-generated'
    message.set_content(body)

    host_cls = smtplib.SMTP_SSL if row.smtp_use_ssl else smtplib.SMTP
    with host_cls(row.smtp_server, row.smtp_port, timeout=20) as host:
        host.ehlo()
        if row.smtp_use_tls and not row.smtp_use_ssl:
            host.starttls()
            host.ehlo()
        if row.smtp_username and password:
            host.login(row.smtp_username, password)
        host.send_message(message, from_addr=sender, to_addrs=recipients)

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- alerting must never raise
        sys.stderr.write('alert failed: %r\n' % (exc,))
        sys.exit(1)
