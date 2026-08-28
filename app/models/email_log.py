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
    # Stale-pending: потік міг уже відправити по SMTP, але не записав 'sent'.
    # Доставка НЕВІДОМА -- авто-ретрай створив би дублі (циклічна розсилка).
    # Лишаємо 'failed'; за потреби адмін пересилає вручну (manual_resend).
    'Timeout: stuck in pending',
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
    # Опціональний ключ ідемпотентності: якщо заданий, повторний send_email з
    # тим самим ключем (статус pending/sent) пропускається -- захист від
    # подвійної відправки на ретраях/гонках (надійніше за 60-секундний дедуп).
    idempotency_key = db.Column(db.String(64), index=True)
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
            "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
            "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
            "'password_reset', 'backup_failure', 'materials', 'referral', "
            "'meta_lead', 'test')",
            name='ck_email_logs_trigger',
        ),
        db.Index('ix_email_logs_created_at', 'created_at'),
        db.Index('ix_email_logs_status_trigger', 'status', 'trigger'),
    )

    STATUSES = [
        ('pending', 'Очікує'),
        ('sent', 'Відправлено'),
        ('failed', 'Помилка'),
    ]

    # Модифікатор `.badge--*` на кожен стан. Раніше стан розкладався
    # тернарником у розмітці, причому по-різному на двох сторінках: журнал
    # писав success/danger/warning, картка сповіщень -- те саме ще раз.
    STATUS_BADGES = {
        'pending': 'pending',
        'sent': 'active',
        'failed': 'cancelled',
    }

    TRIGGERS = [
        ('registration', 'Реєстрація'),
        ('payment', 'Оплата'),
        ('reminder', 'Нагадування'),
        ('status_change', 'Зміна статусу'),
        ('email_confirm', 'Підтвердження email'),
        ('course_request', 'Запит на курс'),
        ('certificate', 'Сертифікат'),
        ('blog_comment', 'Коментар блогу'),
        ('password_reset', 'Відновлення паролю'),
        ('backup_failure', 'Помилка бекапу'),
        ('materials', 'Матеріали заходу'),
        ('referral', 'Реферальний бонус'),
        ('meta_lead', 'Збій приймання лідів Meta'),
        ('test', 'Тест'),
    ]

    # Єдине джерело правди для дозволених тригерів. Має збігатися з CHECK
    # ck_email_logs_trigger; інваріант стереже tests/.../test_trigger_coverage.
    ALLOWED_TRIGGERS = frozenset(code for code, _ in TRIGGERS)

    # НЕОБОВ'ЯЗКОВІ тригери поважають user.email_opt_out і unsubscribe-
    # suppression. Решта -- транзакційне (шлеться завжди).
    OPTIONAL_TRIGGERS = frozenset({'reminder', 'referral'})

    @classmethod
    def is_valid_trigger(cls, trigger):
        return trigger in cls.ALLOWED_TRIGGERS

    @classmethod
    def is_optional_trigger(cls, trigger):
        return trigger in cls.OPTIONAL_TRIGGERS

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def status_badge(self):
        """Модифікатор `.badge--*` під поточний стан (див. STATUS_BADGES)."""
        return self.STATUS_BADGES.get(self.status, 'draft')

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
