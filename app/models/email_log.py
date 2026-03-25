from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class EmailLog(TimestampMixin, db.Model):
    __tablename__ = 'email_logs'

    id = db.Column(BigIntPK, primary_key=True)
    to_email = db.Column(db.String(255), nullable=False, index=True)
    subject = db.Column(db.String(500), nullable=False)
    template_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    error_message = db.Column(db.Text)
    sent_at = db.Column(db.DateTime(timezone=True))
    trigger = db.Column(db.String(50), index=True)
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
            "trigger IN ('registration', 'payment', 'reminder', 'status_change', 'test')",
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
        ('test', 'Тест'),
    ]

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def trigger_label(self):
        return dict(self.TRIGGERS).get(self.trigger, self.trigger or '')

    def __repr__(self):
        return f'<EmailLog {self.id} to={self.to_email} status={self.status}>'
