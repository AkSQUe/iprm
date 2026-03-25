from app.extensions import db
from app.models.mixins import TimestampMixin


class EmailSettings(TimestampMixin, db.Model):
    """Singleton: SMTP settings stored in DB, managed via admin panel."""
    __tablename__ = 'email_settings'

    id = db.Column(db.Integer, primary_key=True, default=1)
    smtp_server = db.Column(db.String(255), default='')
    smtp_port = db.Column(db.Integer, default=465)
    smtp_use_ssl = db.Column(db.Boolean, default=True)
    smtp_use_tls = db.Column(db.Boolean, default=False)
    smtp_username = db.Column(db.String(255), default='')
    smtp_password = db.Column(db.String(255), default='')
    default_sender = db.Column(db.String(255), default='')
    sender_name = db.Column(db.String(255), default='IPRM')
    is_enabled = db.Column(db.Boolean, default=False)
    reminder_days = db.Column(db.String(50), default='7,3,1')

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
