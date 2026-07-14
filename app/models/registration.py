import secrets
from datetime import timedelta, timezone

from sqlalchemy import func as sa_func

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow


# Термін дії токена посилання на самостійне завершення реєстрації учасником.
COMPLETION_TOKEN_TTL_DAYS = 30


class EventRegistration(TimestampMixin, db.Model):
    """Реєстрація на CourseInstance.

    Ім'я класу (EventRegistration) і таблиці (event_registrations)
    збережено з історичних причин -- занадто багато FK і email-логів
    посилаються на них. Насправді тут реєстрація на конкретне
    проведення (CourseInstance).
    """
    __tablename__ = 'event_registrations'

    id = db.Column(BigIntPK, primary_key=True)
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )

    phone = db.Column(db.String(20), nullable=False)
    specialty = db.Column(db.String(200), nullable=False)
    workplace = db.Column(db.String(300), nullable=False)
    experience_years = db.Column(db.Integer)
    license_number = db.Column(db.String(50))

    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    payment_status = db.Column(db.String(20), default='unpaid', nullable=False, index=True)
    # Обраний користувачем спосіб оплати: 'liqpay' (онлайн, за замовчуванням)
    # або 'invoice' (оплата за рахунком через банк). Впливає лише на UX
    # сторінки підтвердження -- фактичний payment_status керується окремо
    # (LiqPay-callback або менеджер). Для безкоштовних подій не релевантний.
    payment_method = db.Column(
        db.String(20), default='liqpay', server_default='liqpay', nullable=False,
    )
    payment_amount = db.Column(db.Numeric(10, 2))
    payment_id = db.Column(db.String(255))
    paid_at = db.Column(db.DateTime(timezone=True))

    # Ідемпотентність авто-нагадування "заповніть дані для сертифіката":
    # один лист на реєстрацію (scheduler-джоба send_certdata_reminders).
    certdata_reminder_sent_at = db.Column(db.DateTime(timezone=True))

    # Обраний тариф участі (тарифна вилка). NULL -- проведення без тарифів
    # або історична реєстрація. Сума фіксується у payment_amount у момент
    # реєстрації, тож видалення/зміна тарифу заднім числом на неї не впливає.
    tariff_id = db.Column(
        db.BigInteger,
        db.ForeignKey('instance_tariffs.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    attended = db.Column(db.Boolean, default=False)
    cpd_points_awarded = db.Column(db.Integer)
    admin_notes = db.Column(db.Text)

    # Реферальна атрибуція: код реферера (User.referral_code або
    # Trainer.referral_code), захоплений з cookie в момент реєстрації.
    # NULL -- реєстрація без реферала. Нарахування бонусів -- у Фазі 3.
    referral_code = db.Column(db.String(32), index=True)

    # Альтернативний pipeline: менеджер створює учасника з мінімумом полів і
    # надсилає посилання з токеном, за яким учасник сам завершує анкету та
    # обирає спосіб оплати. Токен діє COMPLETION_TOKEN_TTL_DAYS; used_at --
    # коли анкету вперше заповнено (інформативно, не блокує повторний вхід).
    completion_token = db.Column(db.String(64), unique=True, index=True)
    completion_token_expires_at = db.Column(db.DateTime(timezone=True))
    completion_token_used_at = db.Column(db.DateTime(timezone=True))

    # Унікальний порядковий номер місця у межах конкретного CourseInstance.
    # Призначається в момент `payment_status='paid'`. Для безкоштовних подій
    # -- одразу при створенні. Унікальність гарантовано partial-index-ом
    # (instance_id, place_number) WHERE place_number IS NOT NULL.
    place_number = db.Column(db.Integer)

    user = db.relationship('User', back_populates='registrations')
    instance = db.relationship(
        'CourseInstance',
        foreign_keys=[instance_id],
        back_populates='registrations',
    )
    tariff = db.relationship('InstanceTariff', foreign_keys=[tariff_id])
    email_logs = db.relationship('EmailLog', back_populates='registration')
    certificate = db.relationship(
        'Certificate',
        back_populates='registration',
        uselist=False,
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.UniqueConstraint('user_id', 'instance_id', name='uq_user_instance_registration'),
        db.Index('ix_registrations_instance_status', 'instance_id', 'status'),
        db.Index('ix_registrations_created_at', 'created_at'),
        # Partial unique index: place_number унікальний у межах instance
        # (NULL дозволено для не-оплачених/скасованих реєстрацій).
        db.Index(
            'uq_registrations_instance_place',
            'instance_id', 'place_number',
            unique=True,
            postgresql_where=db.text('place_number IS NOT NULL'),
        ),
        db.CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled', 'completed')",
            name='ck_registrations_status',
        ),
        db.CheckConstraint(
            "payment_status IN ('unpaid', 'pending', 'paid', 'refunded')",
            name='ck_registrations_payment_status',
        ),
        db.CheckConstraint(
            "payment_method IN ('liqpay', 'invoice')",
            name='ck_registrations_payment_method',
        ),
        db.CheckConstraint(
            'experience_years >= 0',
            name='ck_registrations_experience_non_negative',
        ),
        db.CheckConstraint(
            'cpd_points_awarded >= 0 OR cpd_points_awarded IS NULL',
            name='ck_registrations_cpd_non_negative',
        ),
        db.CheckConstraint(
            'payment_amount >= 0 OR payment_amount IS NULL',
            name='ck_registrations_payment_amount_non_negative',
        ),
    )

    STATUSES = [
        ('pending', 'Очікує'),
        ('confirmed', 'Підтверджено'),
        ('cancelled', 'Скасовано'),
        ('completed', 'Завершено'),
    ]

    PAYMENT_STATUSES = [
        ('unpaid', 'Не оплачено'),
        ('pending', 'Очікує оплати'),
        ('paid', 'Оплачено'),
        ('refunded', 'Повернено'),
    ]

    PAYMENT_METHODS = [
        ('liqpay', 'Онлайн-оплата (LiqPay)'),
        ('invoice', 'Оплата за рахунком'),
    ]

    def issue_completion_token(self, ttl_days=COMPLETION_TOKEN_TTL_DAYS):
        """Згенерувати (або перевипустити) токен завершення реєстрації.

        Повертає рядок токена. Не комітить -- caller відповідає за commit."""
        self.completion_token = secrets.token_urlsafe(32)
        self.completion_token_expires_at = utcnow() + timedelta(days=ttl_days)
        self.completion_token_used_at = None
        return self.completion_token

    def revoke_completion_token(self):
        self.completion_token = None
        self.completion_token_expires_at = None
        self.completion_token_used_at = None

    @property
    def completion_token_active(self):
        """True, якщо токен існує і ще не сплив (used_at не блокує)."""
        if not self.completion_token or self.completion_token_expires_at is None:
            return False
        exp = self.completion_token_expires_at
        if exp.tzinfo is None:  # SQLite повертає naive
            exp = exp.replace(tzinfo=timezone.utc)
        return utcnow() <= exp

    @property
    def user_has_real_email(self):
        """True, якщо в учасника справжній (не placeholder) email -- лише тоді
        посилання на самостійне завершення можна надіслати листом."""
        from app.services.participant_service import is_placeholder_email
        email = self.user.email if self.user else None
        return bool(email and not is_placeholder_email(email))

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def payment_status_label(self):
        return dict(self.PAYMENT_STATUSES).get(self.payment_status, self.payment_status)

    @property
    def payment_method_label(self):
        return dict(self.PAYMENT_METHODS).get(self.payment_method, self.payment_method)

    @classmethod
    def payment_stats(cls):
        return db.session.query(
            sa_func.count(cls.id).label('total'),
            sa_func.count(cls.id).filter(
                cls.payment_status == 'paid'
            ).label('paid'),
            sa_func.count(cls.id).filter(
                cls.payment_status == 'pending'
            ).label('pending'),
            sa_func.count(cls.id).filter(
                cls.payment_status == 'refunded'
            ).label('refunded'),
            sa_func.coalesce(sa_func.sum(
                cls.payment_amount
            ).filter(cls.payment_status == 'paid'), 0).label('total_amount'),
        ).filter(
            cls.payment_amount > 0,
        ).one()

    @property
    def target_title(self):
        if self.instance and self.instance.course:
            return self.instance.course.title
        return ''

    @property
    def target_slug(self):
        if self.instance and self.instance.course:
            return self.instance.course.slug
        return ''

    @property
    def target_start_date(self):
        if self.instance:
            return self.instance.start_date
        return None

    def __repr__(self):
        return f'<EventRegistration user={self.user_id} instance={self.instance_id}>'
