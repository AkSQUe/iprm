"""OnlineEnrollment -- покупка доступу до онлайн-курсу.

Окрема сутність від EventRegistration: там реєстрація на проведення з
датою, містом, місцем, тарифом і сертифікатом БПР. Тут -- разова купівля
доступу до навчання, що йде в Sintegrum.

Платіжний контур спільний (той самий LiqPay і той самий PaymentOps),
відрізняється лише префікс order_id: REG- проти ONL-.

Токен доступу живе тут же, а не в окремій таблиці: він завжди рівно один
на замовлення, і окрема таблиця дала б join заради одного рядка.
"""
import secrets

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow
from app.utils import ensure_utc

# Довжина токена в байтах до base64: 32 байти -- 43 символи URL-safe.
ACCESS_TOKEN_BYTES = 32

STATUS_PENDING = 'pending'
STATUS_ACTIVE = 'active'
STATUS_CANCELLED = 'cancelled'

STATUSES = (STATUS_PENDING, STATUS_ACTIVE, STATUS_CANCELLED)
PAYMENT_STATUSES = ('unpaid', 'pending', 'paid', 'refunded')


class OnlineEnrollment(TimestampMixin, db.Model):
    __tablename__ = 'online_enrollments'

    id = db.Column(BigIntPK, primary_key=True)
    user_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    # RESTRICT, а не CASCADE: курс, за який заплатили, не має зникати з-під
    # замовлення. Зниклі в Sintegrum курси ми й так лише позначаємо.
    online_course_id = db.Column(
        db.BigInteger, db.ForeignKey('online_courses.id', ondelete='RESTRICT'),
        nullable=False, index=True,
    )

    status = db.Column(
        db.String(20), default=STATUS_PENDING, server_default=STATUS_PENDING,
        nullable=False, index=True,
    )
    payment_status = db.Column(
        db.String(20), default='unpaid', server_default='unpaid',
        nullable=False, index=True,
    )
    payment_amount = db.Column(db.Numeric(10, 2))
    payment_id = db.Column(db.String(255))
    payment_method = db.Column(
        db.String(20), default='liqpay', server_default='liqpay', nullable=False,
    )
    paid_at = db.Column(db.DateTime(timezone=True))

    # Промокод, застосований до замовлення. `payment_amount` уже містить суму
    # ПІСЛЯ знижки; `discount_amount` -- знімок того, скільки ми віддали, щоб
    # звіти лишались правдивими навіть після зміни ціни курсу. Історія
    # застосувань (і лічильник) живуть у PromoRedemption.
    promo_code_id = db.Column(
        db.BigInteger, db.ForeignKey('promo_codes.id', ondelete='SET NULL'),
        nullable=True, index=True,
    )
    discount_amount = db.Column(db.Numeric(10, 2))

    # Ідентифікатор учня в Sintegrum. За чинним сценарієм (рішення Q1)
    # лишається порожнім: учень реєструється сам за посиланням. Колонка є
    # під майбутню звірку прогресу за email.
    sintegrum_student_id = db.Column(db.Integer)

    # Коли доступ реально видано (згенеровано токен). Порожньо при
    # payment_status='paid' -- аварійний стан, його підбирає джоба.
    provisioned_at = db.Column(db.DateTime(timezone=True))
    provision_error = db.Column(db.Text)

    access_token = db.Column(db.String(64), unique=True, index=True)
    access_expires_at = db.Column(db.DateTime(timezone=True))
    access_issued_count = db.Column(
        db.Integer, default=0, server_default='0', nullable=False,
    )
    access_last_opened_at = db.Column(db.DateTime(timezone=True))

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'active', 'cancelled')",
            name='ck_online_enrollments_status',
        ),
        db.CheckConstraint(
            "payment_status IN ('unpaid', 'pending', 'paid', 'refunded')",
            name='ck_online_enrollments_payment_status',
        ),
        db.CheckConstraint(
            'payment_amount >= 0 OR payment_amount IS NULL',
            name='ck_online_enrollments_amount_non_negative',
        ),
        # Одна людина -- одна діюча покупка курсу. Часткова унікальність, бо
        # скасоване замовлення не має блокувати повторну купівлю.
        db.Index(
            'uq_online_enrollments_user_course_live',
            'user_id', 'online_course_id',
            unique=True,
            postgresql_where=db.text("status <> 'cancelled'"),
            sqlite_where=db.text("status <> 'cancelled'"),
        ),
        db.Index('ix_online_enrollments_paid_unprovisioned',
                 'payment_status', 'provisioned_at'),
    )

    user = db.relationship('User', backref=db.backref(
        'online_enrollments', lazy='dynamic'))
    # foreign_keys обов'язкові: між таблицями тепер ДВА шляхи --
    # online_enrollments.promo_code_id (застосований код) і
    # promo_codes.issued_for_enrollment_id (код, виданий за цю покупку).
    promo_code = db.relationship(
        'PromoCode', foreign_keys=[promo_code_id])
    promo_redemptions = db.relationship(
        'PromoRedemption', back_populates='enrollment', lazy='dynamic')
    course = db.relationship('OnlineCourse', backref=db.backref(
        'enrollments', lazy='dynamic'))

    # ---- гроші ----

    @property
    def order_id(self):
        return f'ONL-{self.id}'

    @property
    def is_paid(self):
        return self.payment_status == 'paid'

    # ---- доступ ----

    @property
    def access_is_valid(self):
        """Чи можна просто зараз пройти за виданим посиланням."""
        if not self.is_paid or not self.access_token:
            return False
        if self.access_expires_at is None:
            return False
        return ensure_utc(self.access_expires_at) > utcnow()

    @property
    def access_is_expired(self):
        return bool(
            self.access_token
            and self.access_expires_at is not None
            and ensure_utc(self.access_expires_at) <= utcnow()
        )

    def issue_access_token(self, ttl_hours):
        """Видати новий токен. Попередній тієї ж миті стає недійсним."""
        from datetime import timedelta

        self.access_token = secrets.token_urlsafe(ACCESS_TOKEN_BYTES)
        self.access_expires_at = utcnow() + timedelta(hours=ttl_hours)
        self.access_issued_count = (self.access_issued_count or 0) + 1
        return self.access_token

    def revoke_access(self):
        self.access_token = None
        self.access_expires_at = None

    def __repr__(self):
        return f'<OnlineEnrollment {self.order_id} {self.payment_status}>'
