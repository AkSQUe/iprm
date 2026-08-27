import secrets
from datetime import timedelta, timezone

from sqlalchemy import func as sa_func

from app.extensions import db
from app.models.mixins import (
    TimestampMixin, BigIntPK, DiscountedMixin, RefundableMixin, utcnow,
)


# Термін дії токена посилання на самостійне завершення реєстрації учасником.
COMPLETION_TOKEN_TTL_DAYS = 30


class EventRegistration(TimestampMixin, RefundableMixin, DiscountedMixin,
                        db.Model):
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

    # Повернення коштів -- колонки й правила у RefundableMixin.

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

    # Промокод, застосований до цієї реєстрації (NULL -- без знижки).
    # payment_amount уже містить суму ПІСЛЯ знижки; discount_amount --
    # знімок того, скільки ми віддали, щоб звіти лишались правдивими
    # навіть після зміни тарифу чи видалення коду. Історія застосувань
    # (і лічильник) живуть у PromoRedemption.
    promo_code_id = db.Column(
        db.BigInteger,
        db.ForeignKey('promo_codes.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    discount_amount = db.Column(db.Numeric(10, 2))

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

    # Коли планувальник має надіслати лист "Реєстрацію підтверджено".
    # Заповнюється ЛИШЕ публічним чекаутом для реєстрацій, за які ще треба
    # платити; знімається після надсилання або коли оплата прийшла раніше.
    # Окрема колонка, а не пошук по email_logs: інакше під розсилку
    # потрапили б реєстрації, заведені адміном чи xlsx-імпортом, яким цей
    # лист не призначався.
    confirmation_email_due_at = db.Column(
        db.DateTime(timezone=True), index=True,
    )

    # Тестування після заходу. Денормалізація заради лістингів і гейта: інакше
    # кожен рядок реєстрації в адмінці й кабінеті тягнув би за собою вибірку
    # спроб. Джерело правди лишається у quiz_attempts.
    quiz_passed_at = db.Column(db.DateTime(timezone=True))
    # Додаткові спроби, видані адміном понад CourseQuiz.max_attempts (технічний
    # збій, спірний випадок). Саме число, а не прапорець «розблоковано»: інакше
    # неможливо було б дати рівно одну спробу.
    quiz_extra_attempts = db.Column(
        db.Integer, nullable=False, default=0, server_default='0',
    )

    user = db.relationship('User', back_populates='registrations')
    instance = db.relationship(
        'CourseInstance',
        foreign_keys=[instance_id],
        back_populates='registrations',
    )
    tariff = db.relationship('InstanceTariff', foreign_keys=[tariff_id])
    promo_code = db.relationship('PromoCode', foreign_keys=[promo_code_id])
    # Список, а не один об'єкт: заміна коду чи повернення коштів лишають
    # анульовані рядки в історії поруч із активним (partial-unique index
    # на promo_redemptions стежить, щоб активний був лише один).
    promo_redemptions = db.relationship(
        'PromoRedemption',
        back_populates='registration',
        cascade='all, delete-orphan',
    )
    email_logs = db.relationship('EmailLog', back_populates='registration')
    certificate = db.relationship(
        'Certificate',
        back_populates='registration',
        uselist=False,
        cascade='all, delete-orphan',
    )
    quiz_attempts = db.relationship(
        'QuizAttempt',
        back_populates='registration',
        cascade='all, delete-orphan',
        order_by='QuizAttempt.attempt_number',
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
        db.CheckConstraint(
            'discount_amount >= 0 OR discount_amount IS NULL',
            name='ck_registrations_discount_non_negative',
        ),
        db.CheckConstraint(
            'refunded_amount >= 0',
            name='ck_event_registrations_refunded_amount_non_negative',
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

    # Модифікатор `.badge--*` на кожен стан. Тримається тут, поруч зі
    # `status_label`, а не в шаблоні: `badge--{{ reg.status }}` навпростець
    # давав «Підтверджено» без тла -- модифікатора `confirmed` у системі немає.
    #   pending   -- сірий: заявка є, підтвердження ще немає;
    #   confirmed -- синій: підтверджено, попереду сам захід;
    #   completed -- зелений: цикл закритий;
    #   cancelled -- червоний.
    STATUS_BADGES = {
        'pending': 'pending',
        'confirmed': 'published',
        'cancelled': 'cancelled',
        'completed': 'active',
    }

    # Оплата -- окрема вісь від статусу реєстрації: людина може бути
    # підтверджена й не оплачена. Це відображення двічі стояло тернарником
    # просто в розмітці -- в instance_registrations.html і в liqpay.html, і
    # дослівно однаковим.
    PAYMENT_BADGES = {
        'unpaid': 'draft',
        'pending': 'published',
        'paid': 'active',
        'refunded': 'cancelled',
    }

    @property
    def status_badge(self):
        """Модифікатор `.badge--*` під статус реєстрації."""
        return self.STATUS_BADGES.get(self.status, 'draft')

    @property
    def payment_badge(self):
        """Модифікатор `.badge--*` під статус оплати."""
        return self.PAYMENT_BADGES.get(self.payment_status, 'draft')

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
            # Дохід -- ЗА ВИРАХУВАННЯМ повернень. Часткове повернення лишає
            # реєстрацію в статусі 'paid', тож без цього віднімання
            # повернені гроші й далі рахувались би виручкою.
            sa_func.coalesce(sa_func.sum(
                cls.payment_amount - sa_func.coalesce(cls.refunded_amount, 0)
            ).filter(cls.payment_status == 'paid'), 0).label('total_amount'),
            # Повернене -- по ВСІХ рядках, а не лише зі статусом 'refunded':
            # частково повернені лишаються 'paid' і випали б зі звіту.
            sa_func.coalesce(sa_func.sum(
                cls.refunded_amount
            ), 0).label('refunded_amount'),
        ).filter(
            cls.payment_amount > 0,
        ).one()

    @property
    def awaiting_payment(self):
        """True, поки платіжний шлях не завершено (не сплачено або в обробці).

        Екрани реєстрації ховають усе, що відволікає від оплати, поки це
        True -- зокрема блок рекомендованих курсів.
        """
        if not (self.payment_amount and self.payment_amount > 0):
            return False
        return self.payment_status in ('unpaid', 'pending')

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
