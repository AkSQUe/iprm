import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from app.extensions import db
from app.models.mixins import TimestampMixin

logger = logging.getLogger(__name__)


def _get_fernet():
    """Derive Fernet key from Flask SECRET_KEY."""
    secret = current_app.config['SECRET_KEY']
    key = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


class EmailSettings(TimestampMixin, db.Model):
    """Singleton: SMTP settings stored in DB, managed via admin panel."""
    __tablename__ = 'email_settings'

    id = db.Column(db.Integer, primary_key=True, default=1)
    smtp_server = db.Column(db.String(255), default='')
    smtp_port = db.Column(db.Integer, default=465)
    smtp_use_ssl = db.Column(db.Boolean, default=True)
    smtp_use_tls = db.Column(db.Boolean, default=False)
    smtp_username = db.Column(db.String(255), default='')
    _smtp_password_encrypted = db.Column('smtp_password', db.String(500), default='')
    default_sender = db.Column(db.String(255), default='')
    sender_name = db.Column(db.String(255), default='IPRM')
    is_enabled = db.Column(db.Boolean, default=False)
    reminder_days = db.Column(db.String(50), default='7,3,1')

    __table_args__ = (
        db.CheckConstraint('smtp_port > 0', name='ck_email_settings_port'),
    )

    @property
    def smtp_password(self):
        """Decrypt password from DB."""
        if not self._smtp_password_encrypted:
            return ''
        try:
            f = _get_fernet()
            return f.decrypt(self._smtp_password_encrypted.encode()).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt SMTP password, returning empty')
            return ''

    @smtp_password.setter
    def smtp_password(self, value):
        """Encrypt password before storing."""
        if not value:
            self._smtp_password_encrypted = ''
            return
        f = _get_fernet()
        self._smtp_password_encrypted = f.encrypt(value.encode()).decode()

    @classmethod
    def get(cls):
        """Get or create singleton settings row."""
        settings = cls.query.get(1)
        if not settings:
            settings = cls(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings

    @property
    def has_password(self):
        return bool(self._smtp_password_encrypted)

    @property
    def reminder_days_list(self):
        if not self.reminder_days:
            return [7, 3, 1]
        return [int(d.strip()) for d in self.reminder_days.split(',') if d.strip().isdigit()]

    def apply_to_app(self, app):
        """Push current DB settings into Flask-Mail config."""
        app.config['MAIL_SERVER'] = self.smtp_server
        app.config['MAIL_PORT'] = self.smtp_port
        app.config['MAIL_USE_SSL'] = self.smtp_use_ssl
        app.config['MAIL_USE_TLS'] = self.smtp_use_tls
        app.config['MAIL_USERNAME'] = self.smtp_username
        app.config['MAIL_PASSWORD'] = self.smtp_password
        if self.sender_name and self.default_sender:
            app.config['MAIL_DEFAULT_SENDER'] = (self.sender_name, self.default_sender)
        elif self.default_sender:
            app.config['MAIL_DEFAULT_SENDER'] = self.default_sender
        app.config['MAIL_SUPPRESS_SEND'] = not self.is_enabled

    def __repr__(self):
        return f'<EmailSettings smtp={self.smtp_server}:{self.smtp_port}>'
