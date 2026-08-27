"""PromoCode + PromoRedemption -- промокоди зі знижкою на реєстрацію.

Навіщо (кейси Дмитра, 06.08.2026):
  * персональна знижка/безкоштовний доступ конкретній людині ("забутий"
    учасник, колега тренера) -- код на 1 використання;
  * B2B: фарма проплатила рекламу і просить запросити N лікарів
    безкоштовно або зі знижкою -- код на N використань, прив'язаний до
    конкретного курсу чи проведення;
  * комплексна пропозиція клінікам (пробірки на 60+ тис) -- 1-2 лікарі
    безкоштовно;
  * тест механіки реєстрації та автолистів -- код на 100%.

Знижка фіксована: або відсоток (1-100), або сума в гривнях. Ліміти два --
загальний (max_uses) і на одну людину (per_user_limit); NULL в обох
означає "без обмежень". Термін дії -- опційне вікно valid_from/valid_until.

Списання рахуємо не лічильником, а реєстром PromoRedemption: один рядок =
одне застосування до однієї реєстрації (partial-unique index гарантує, що
активне списання на реєстрацію рівно одне, а анульовані лишаються в
історії). used_count -- денормалізація для швидких перевірок і
списків; джерело правди -- реєстр, звідки його можна перерахувати
(promo_service.recount).
"""
from decimal import Decimal, ROUND_HALF_UP

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow
from app.services.money import format_amount
from app.utils import ensure_utc


DISCOUNT_PERCENT = 'percent'
DISCOUNT_AMOUNT = 'amount'


class PromoCode(TimestampMixin, db.Model):
    __tablename__ = 'promo_codes'

    id = db.Column(BigIntPK, primary_key=True)

    # code -- як його ввів адмін (показуємо в UI, друкуємо в листах).
    # code_norm -- ключ пошуку: casefold + без пробілів. Саме він
    # унікальний, тож "Дмитро", "дмитро" і "ДМИТРО" -- один код.
    code = db.Column(db.String(64), nullable=False)
    code_norm = db.Column(db.String(64), nullable=False, unique=True, index=True)

    # Для кого/навіщо виданий -- підказка менеджеру в списку.
    description = db.Column(db.String(255))

    discount_type = db.Column(
        db.String(10), nullable=False, server_default=DISCOUNT_PERCENT,
    )
    discount_value = db.Column(db.Numeric(10, 2), nullable=False)

    # NULL -- без обмежень. max_uses рахує ВСІ застосування коду,
    # per_user_limit -- застосування одним користувачем.
    #
    # Ні Python-, ні server-дефолту тут навмисно НЕМАЄ: на явне None ORM
    # підставив би дефолт (або пропустив колонку в INSERT на користь
    # server_default), і "без обмежень" з адмін-форми мовчки стало б
    # "1 раз". Дефолт "1" живе у PromoCodeForm, де його видно людині.
    max_uses = db.Column(db.Integer)
    per_user_limit = db.Column(db.Integer)
    used_count = db.Column(
        db.Integer, nullable=False, default=0, server_default='0',
    )

    valid_from = db.Column(db.DateTime(timezone=True))
    valid_until = db.Column(db.DateTime(timezone=True))

    # Область дії: обидва NULL -- код діє на будь-яку реєстрацію; course_id --
    # на всі проведення курсу; instance_id -- на одне проведення.
    course_id = db.Column(
        db.BigInteger,
        db.ForeignKey('courses.id', ondelete='CASCADE'),
        index=True,
    )
    instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='CASCADE'),
        index=True,
    )

    is_active = db.Column(
        db.Boolean, nullable=False, default=True, server_default=db.text('true'),
    )

    created_by_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
    )

    # Реєстрація, ЗА ЯКУ код видано автоматично (промокод-подяка в листі про
    # оплату). Не область дії, а походження: по ньому робимо видачу
    # ідемпотентною (повторний лист не плодить кодів) і видно в адмінці,
    # звідки код узявся. NULL -- код заведений руками.
    #
    # use_alter: event_registrations уже посилається на promo_codes, тож пряме
    # оголошення дало б цикл, який SQLAlchemy не вміє відсортувати при
    # create_all. Обмеження навішується окремим ALTER після обох таблиць.
    issued_for_registration_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            'event_registrations.id', ondelete='SET NULL',
            use_alter=True, name='fk_promo_codes_issued_for_registration',
        ),
        index=True,
    )
    # Те саме для покупок онлайн-курсів. Nullable і без CHECK «рівно одне
    # з двох»: код може бути й загальним, не виданим ні за що конкретне --
    # саме такі створює адмін руками. Ці колонки означають «за що видано»,
    # а не власника коду.
    # use_alter -- з тієї ж причини, що й вище: online_enrollments уже
    # посилається на promo_codes (застосований код), тож пряме оголошення
    # замикає цикл, і create_all/drop_all не можуть відсортувати таблиці.
    issued_for_enrollment_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            'online_enrollments.id', ondelete='SET NULL',
            use_alter=True, name='fk_promo_codes_issued_for_enrollment',
        ),
        nullable=True, index=True,
    )

    course = db.relationship('Course')
    instance = db.relationship('CourseInstance')
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    issued_for_enrollment = db.relationship(
        'OnlineEnrollment', foreign_keys=[issued_for_enrollment_id],
    )
    issued_for_registration = db.relationship(
        'EventRegistration', foreign_keys=[issued_for_registration_id],
    )
    redemptions = db.relationship(
        'PromoRedemption',
        back_populates='promo_code',
        cascade='all, delete-orphan',
        passive_deletes=True,
    )

    __table_args__ = (
        db.CheckConstraint(
            "discount_type IN ('percent', 'amount')",
            name='ck_promo_codes_discount_type',
        ),
        db.CheckConstraint(
            'discount_value > 0', name='ck_promo_codes_discount_positive',
        ),
        # Відсоток не може перевищувати 100; для сум стеля не потрібна --
        # знижка все одно обрізається сумою замовлення.
        db.CheckConstraint(
            "discount_type <> 'percent' OR discount_value <= 100",
            name='ck_promo_codes_percent_range',
        ),
        db.CheckConstraint(
            'max_uses IS NULL OR max_uses >= 1', name='ck_promo_codes_max_uses',
        ),
        db.CheckConstraint(
            'per_user_limit IS NULL OR per_user_limit >= 1',
            name='ck_promo_codes_per_user_limit',
        ),
        db.CheckConstraint('used_count >= 0', name='ck_promo_codes_used_count'),
        # Індексів за is_active/valid_until немає навмисно: кодів завжди
        # десятки, а єдиний гарячий шлях -- пошук за code_norm (унікальний
        # індекс вище). Адмін-список і так читає таблицю цілком.
    )

    DISCOUNT_TYPES = [
        (DISCOUNT_PERCENT, 'Відсоток (%)'),
        (DISCOUNT_AMOUNT, 'Фіксована сума (грн)'),
    ]

    # ---------- розрахунок знижки ----------

    def discount_for(self, amount):
        """Скільки грн знижки дає код для суми `amount`.

        Ніколи не більше самої суми (100% -- максимум) і не менше нуля.
        """
        base = Decimal(amount or 0)
        if base <= 0:
            return Decimal('0.00')
        value = Decimal(self.discount_value or 0)
        if self.discount_type == DISCOUNT_PERCENT:
            raw = base * value / Decimal(100)
        else:
            raw = value
        raw = raw.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return min(max(raw, Decimal('0.00')), base)

    def final_for(self, amount):
        """Сума до сплати після знижки."""
        base = Decimal(amount or 0)
        if base <= 0:
            return Decimal('0.00')
        return base - self.discount_for(base)

    # ---------- стан ----------

    @property
    def uses_left(self):
        """Скільки застосувань лишилось; None -- безліміт."""
        if self.max_uses is None:
            return None
        return max(0, self.max_uses - (self.used_count or 0))

    @property
    def is_exhausted(self):
        return self.max_uses is not None and (self.used_count or 0) >= self.max_uses

    @property
    def is_not_started(self):
        start = ensure_utc(self.valid_from)
        return start is not None and utcnow() < start

    @property
    def is_expired(self):
        end = ensure_utc(self.valid_until)
        return end is not None and utcnow() > end

    @property
    def is_usable(self):
        """Чи придатний код узагалі (без урахування курсу й користувача)."""
        return (self.is_active and not self.is_exhausted
                and not self.is_expired and not self.is_not_started)

    @property
    def status_label(self):
        if not self.is_active:
            return 'Вимкнено'
        if self.is_exhausted:
            return 'Вичерпано'
        if self.is_expired:
            return 'Термін минув'
        if self.is_not_started:
            return 'Ще не почався'
        return 'Активний'

    @property
    def status_badge(self):
        return 'badge--active' if self.is_usable else 'badge--draft'

    @property
    def discount_label(self):
        """«10%» або «2 000 ₴».

        Сума -- тим самим форматувальником і тим самим символом, що всюди на
        сайті: код на 2000 друкувався тут як «2000 грн», а та сама сума в
        сусідній колонці й у листі -- як «2 000 ₴».
        """
        value = Decimal(self.discount_value or 0)
        if self.discount_type == DISCOUNT_PERCENT:
            # 50.00 -> "50", 12.50 -> "12.5"
            return f"{format(value.normalize(), 'f')}%"
        return f'{format_amount(value)} ₴'

    @property
    def usage_label(self):
        used = self.used_count or 0
        if self.max_uses is None:
            return f'{used} / ∞'
        return f'{used} / {self.max_uses}'

    @property
    def scope_label(self):
        if self.instance is not None:
            title = (self.instance.course.title if self.instance.course
                     else f'Проведення #{self.instance_id}')
            date = (self.instance.start_date.strftime('%d.%m.%Y')
                    if self.instance.start_date else 'без дати')
            return f'{title} — {date}'
        if self.course is not None:
            return self.course.title
        return 'Усі курси'

    def __repr__(self):
        return f'<PromoCode {self.code} {self.discount_label} {self.usage_label}>'


class PromoRedemption(TimestampMixin, db.Model):
    """Одне застосування промокоду до однієї реєстрації.

    Зберігаємо не лише знижку, а й суму до/після: тариф чи ціна проведення
    можуть змінитися заднім числом, а звіт "скільки ми віддали знижками"
    має лишатись правдивим.
    """
    __tablename__ = 'promo_redemptions'

    id = db.Column(BigIntPK, primary_key=True)

    promo_code_id = db.Column(
        db.BigInteger,
        db.ForeignKey('promo_codes.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    # Рівно одне з двох посилань заповнене: реєстр спільний для обох типів
    # замовлень. Розводити їх по таблицях означало б, що код із max_uses=1
    # можна використати двічі -- по разу в кожному типі.
    registration_id = db.Column(
        db.BigInteger,
        db.ForeignKey('event_registrations.id', ondelete='CASCADE'),
        nullable=True, index=True,
    )
    enrollment_id = db.Column(
        db.BigInteger,
        db.ForeignKey('online_enrollments.id', ondelete='CASCADE'),
        nullable=True, index=True,
    )
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        index=True,
    )

    original_amount = db.Column(db.Numeric(10, 2), nullable=False)
    discount_amount = db.Column(db.Numeric(10, 2), nullable=False)
    final_amount = db.Column(db.Numeric(10, 2), nullable=False)

    # 'applied' -- активне (враховується в лічильнику);
    # 'voided' -- анульоване (повернення коштів, скасування, зміна коду).
    status = db.Column(
        db.String(10), nullable=False, default='applied',
        server_default='applied', index=True,
    )
    voided_at = db.Column(db.DateTime(timezone=True))
    notes = db.Column(db.String(255))

    promo_code = db.relationship('PromoCode', back_populates='redemptions')
    registration = db.relationship('EventRegistration', back_populates='promo_redemptions')
    enrollment = db.relationship('OnlineEnrollment', back_populates='promo_redemptions')
    user = db.relationship('User')

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('applied', 'voided')", name='ck_promo_redemptions_status',
        ),
        db.CheckConstraint(
            'discount_amount >= 0', name='ck_promo_redemptions_discount_non_negative',
        ),
        # Ліміт "на одну людину" рахуємо саме по цьому індексу.
        db.Index('ix_promo_redemptions_code_user', 'promo_code_id', 'user_id', 'status'),
        # Активне списання на реєстрацію -- рівно одне (ідемпотентність),
        # але анульовані рядки лишаються в історії: заміна коду чи
        # повернення коштів не мають стирати те, що вже сталося.
        db.Index(
            'uq_promo_redemptions_active_reg', 'registration_id',
            unique=True,
            postgresql_where=db.text("status = 'applied'"),
            sqlite_where=db.text("status = 'applied'"),
        ),
        # Дзеркало попереднього для замовлень онлайн-курсів.
        db.Index(
            'uq_promo_redemptions_active_enrollment', 'enrollment_id',
            unique=True,
            postgresql_where=db.text("status = 'applied'"),
            sqlite_where=db.text("status = 'applied'"),
        ),
        db.CheckConstraint(
            '(registration_id IS NULL) <> (enrollment_id IS NULL)',
            name='ck_promo_redemptions_single_owner',
        ),
    )

    STATUSES = [
        ('applied', 'Застосовано'),
        ('voided', 'Анульовано'),
    ]

    def void(self, reason=None):
        """Перевести застосування в анульоване. Не комітить."""
        self.status = 'voided'
        self.voided_at = utcnow()
        if reason:
            self.notes = reason[:255]

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    def __repr__(self):
        return (f'<PromoRedemption promo={self.promo_code_id} '
                f'reg={self.registration_id} -{self.discount_amount} {self.status}>')
