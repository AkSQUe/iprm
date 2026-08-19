"""RefundRequest -- заявка учасника на повернення коштів.

Політика (розділ 6) вимагає письмову заявку з причиною відмови, а §4.2
прямо каже: відсоток рахується від ДАТИ ПОДАННЯ заявки. Доти цієї дати в
системі не існувало -- адмін відкривав сторінку повернення й отримував
сходинку на момент кліку. Заявка, що пролежала в пошті три дні, коштувала
учаснику половини суми.

Тому тут не просто форма, а фіксація моменту: `created_at` -- і є дата
подання, а `quoted_*` -- знімок політики на цю мить. Знімок, а не
перерахунок при відкритті: дата заходу може змінитись (перенесення, §3), і
жива формула дала б іншу відповідь, ніж та, яку учасник бачив, коли
подавав заявку.

Гроші звідси не рухаються. Рішення про суму й саме повернення лишаються на
сторінці `/admin/refunds/...`: два шляхи до руху грошей -- два місця, де
можна помилитись.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow

STATUS_NEW = 'new'
STATUS_APPROVED = 'approved'
STATUS_REJECTED = 'rejected'


class RefundRequest(TimestampMixin, db.Model):
    __tablename__ = 'refund_requests'

    id = db.Column(BigIntPK, primary_key=True)

    # Рівно одне з двох заповнене -- як у payment_transactions: заявки на
    # обидва типи замовлень мають читатися однією чергою, інакше половина
    # завжди лишатиметься поза очима адміна.
    registration_id = db.Column(
        db.BigInteger, db.ForeignKey('event_registrations.id', ondelete='CASCADE'),
        nullable=True, index=True,
    )
    enrollment_id = db.Column(
        db.BigInteger, db.ForeignKey('online_enrollments.id', ondelete='CASCADE'),
        nullable=True, index=True,
    )
    user_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )

    # §6.2: причина відмови від участі -- обов'язкова.
    reason = db.Column(db.Text, nullable=False)
    # §6.2: реквізити, якщо повернення має піти на інший рахунок. Порожньо --
    # повертаємо тим самим способом оплати (§7.2), як і має бути за умовчанням.
    payout_details = db.Column(db.String(500))

    status = db.Column(
        db.String(20), default=STATUS_NEW, server_default=STATUS_NEW,
        nullable=False, index=True,
    )

    # Знімок політики на момент подання (§4.2).
    quoted_percent = db.Column(db.Integer)
    quoted_amount = db.Column(db.Numeric(10, 2))
    quoted_code = db.Column(db.String(30))

    decided_at = db.Column(db.DateTime(timezone=True))
    decided_by_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    decision_note = db.Column(db.String(500))

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('new', 'approved', 'rejected')",
            name='ck_refund_requests_status',
        ),
        db.CheckConstraint(
            '(registration_id IS NULL) <> (enrollment_id IS NULL)',
            name='ck_refund_requests_single_owner',
        ),
        # Одна відкрита заявка на замовлення. Без цього повторний клік по
        # кнопці (або нетерплячий учасник) плодив би чергу дублів, у якій
        # адмін мусив би вгадувати, яку саме розглядати.
        db.Index(
            'uq_refund_requests_open_registration',
            'registration_id', unique=True,
            postgresql_where=db.text("status = 'new' AND registration_id IS NOT NULL"),
            sqlite_where=db.text("status = 'new' AND registration_id IS NOT NULL"),
        ),
        db.Index(
            'uq_refund_requests_open_enrollment',
            'enrollment_id', unique=True,
            postgresql_where=db.text("status = 'new' AND enrollment_id IS NOT NULL"),
            sqlite_where=db.text("status = 'new' AND enrollment_id IS NOT NULL"),
        ),
        db.Index('ix_refund_requests_created_at', 'created_at'),
    )

    registration = db.relationship('EventRegistration')
    enrollment = db.relationship('OnlineEnrollment')
    user = db.relationship('User', foreign_keys=[user_id])
    decided_by = db.relationship('User', foreign_keys=[decided_by_id])

    STATUSES = [
        (STATUS_NEW, 'Нова'),
        (STATUS_APPROVED, 'Задоволена'),
        (STATUS_REJECTED, 'Відхилена'),
    ]

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def order(self):
        """Замовлення, якого стосується заявка, без зайвого розгалуження."""
        return self.registration or self.enrollment

    @property
    def order_code(self):
        if self.enrollment_id:
            return self.enrollment.order_id if self.enrollment else f'ONL-{self.enrollment_id}'
        return f'REG-{self.registration_id}'

    @property
    def kind(self):
        """Значення для URL сторінки повернення."""
        return 'enrollment' if self.enrollment_id else 'registration'

    @property
    def is_open(self):
        return self.status == STATUS_NEW

    @property
    def title(self):
        """Назва заходу чи курсу -- для черги й листів."""
        if self.enrollment_id:
            course = self.enrollment.course if self.enrollment else None
            return course.effective_title if course else 'Онлайн-курс'
        reg = self.registration
        return (reg.target_title if reg else '') or 'Захід'

    def decide(self, status, admin_user, note=None):
        """Зафіксувати рішення. Не комітить."""
        self.status = status
        self.decided_at = utcnow()
        self.decided_by_id = admin_user.id if admin_user else None
        if note:
            self.decision_note = note[:500]

    def __repr__(self):
        return f'<RefundRequest {self.id} {self.order_code} {self.status}>'
