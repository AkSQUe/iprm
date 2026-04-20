"""WebhookDelivery — черга партнерських webhook-доставок.

Listener на Course/CourseInstance INSERT-ить рядок у цю таблицю замість
безпосереднього HTTP POST. Dispatcher (scheduler job) періодично читає
pending / retrying-рядки й відправляє їх. Переваги:

* Видимість: адмін бачить історію і стан;
* Надійність: при рестарті/crash pending-записи не губляться;
* Retry: circuit breaker + exponential backoff без втрат;
* Audit: хто/коли/що -- для розбору розбіжностей із партнером.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


MAX_ATTEMPTS = 5
INITIAL_BACKOFF_SECONDS = 60  # 1 хв, потім 2, 4, 8, 16 (exp backoff)


class WebhookDelivery(TimestampMixin, db.Model):
    __tablename__ = 'webhook_deliveries'

    id = db.Column(BigIntPK, primary_key=True)

    # Snapshot даних про course на момент події. Причина snapshot-ити
    # slug та course_id -- партнер отримає правильні дані навіть якщо
    # курс до моменту надсилання видалили/перейменували.
    course_id = db.Column(db.BigInteger, nullable=False, index=True)
    course_slug = db.Column(db.String(200), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # created/updated/deleted

    # Ідемпотентний ідентифікатор для партнера (set один раз на вставці).
    event_uuid = db.Column(db.String(32), nullable=False, unique=True, index=True)

    # Target URL snapshot -- щоб зміна `partner_webhook_url` у SiteSettings
    # не впливала на вже згенеровані delivery-рядки.
    target_url = db.Column(db.String(500), nullable=False)

    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    # 'pending' -- ще не намагалися відправити
    # 'sent' -- успішно (2xx від партнера)
    # 'failed' -- остаточно (досягнуто MAX_ATTEMPTS або permanent error)
    # 'retrying' -- transient fail, next_retry_at задано

    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text)
    last_http_status = db.Column(db.Integer)

    next_retry_at = db.Column(db.DateTime(timezone=True), index=True)
    sent_at = db.Column(db.DateTime(timezone=True))

    __table_args__ = (
        db.Index('ix_webhook_deliveries_status_retry', 'status', 'next_retry_at'),
        db.CheckConstraint(
            "action IN ('created', 'updated', 'deleted')",
            name='ck_webhook_deliveries_action',
        ),
        db.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'retrying')",
            name='ck_webhook_deliveries_status',
        ),
        db.CheckConstraint(
            'attempts >= 0',
            name='ck_webhook_deliveries_attempts_non_negative',
        ),
    )

    @property
    def is_terminal(self):
        """True якщо запис не потребує подальших спроб."""
        return self.status in ('sent', 'failed')

    def __repr__(self):
        return (
            f'<WebhookDelivery id={self.id} course={self.course_slug} '
            f'action={self.action} status={self.status} attempts={self.attempts}>'
        )
