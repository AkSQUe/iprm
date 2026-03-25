from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK

# Emails older than this (minutes) in "pending" are considered stuck.
STALE_PENDING_MINUTES = 5

# Maximum retry attempts for transient SMTP failures.
MAX_RETRIES = 3

# Errors that should NOT be retried (permanent failures).
PERMANENT_ERROR_MARKERS = (
    'disabled in settings',
    'Template render error',
    'Authentication',
    '535 ',
    '550 ',
    '553 ',
    '554 ',
)


class EmailLog(TimestampMixin, db.Model):
    __tablename__ = 'email_logs'

    id = db.Column(BigIntPK, primary_key=True)
    to_email = db.Column(db.String(255), nullable=False, index=True)
    subject = db.Column(db.String(500), nullable=False)
    template_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    error_message = db.Column(db.Text)
    html_body = db.Column(db.Text)
    sent_at = db.Column(db.DateTime(timezone=True))
    trigger = db.Column(db.String(50), index=True)
    retry_count = db.Column(db.Integer, default=0, nullable=False)
    registration_id = db.Column(
        db.BigInteger,
        db.ForeignKey('event_registrations.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    registration = db.relationship(
        'EventRegistration', back_populates='email_logs',
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name='ck_email_logs_status',
        ),
        db.CheckConstraint(
            "trigger IN ('registration', 'payment', 'reminder', 'status_change', 'email_confirm', 'test')",
            name='ck_email_logs_trigger',
        ),
        db.Index('ix_email_logs_created_at', 'created_at'),
    )

    STATUSES = [
        ('pending', 'Очікує'),
        ('sent', 'Відправлено'),
        ('failed', 'Помилка'),
    ]

    TRIGGERS = [
        ('registration', 'Реєстрація'),
        ('payment', 'Оплата'),
        ('reminder', 'Нагадування'),
        ('status_change', 'Зміна статусу'),
        ('email_confirm', 'Підтвердження email'),
        ('test', 'Тест'),
    ]

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def trigger_label(self):
        return dict(self.TRIGGERS).get(self.trigger, self.trigger or '')

    @property
    def is_retryable(self):
        """True if this failed email can be retried."""
        if self.status != 'failed':
            return False
        if self.retry_count >= MAX_RETRIES:
            return False
        if self.trigger == 'test':
            return False
        err = self.error_message or ''
        return not any(marker in err for marker in PERMANENT_ERROR_MARKERS)

    def __repr__(self):
        return f'<EmailLog {self.id} to={self.to_email} status={self.status} retry={self.retry_count}>'
