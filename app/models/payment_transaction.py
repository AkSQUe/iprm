from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class PaymentTransaction(TimestampMixin, db.Model):
    """Журнал всіх платіжних операцій LiqPay.

    Зберігає кожну подію (callback, перевірка статусу, повернення)
    як окремий запис для повного аудиту.
    """

    __tablename__ = 'payment_transactions'

    id = db.Column(BigIntPK, primary_key=True)
    # Рівно одне з двох посилань заповнене: журнал спільний для обох типів
    # замовлень (REG- -- реєстрація на захід, ONL- -- купівля онлайн-курсу).
    # Розділяти журнали не можна: звірка платежів має читатися одним
    # запитом, інакше половина операцій завжди лишатиметься поза звітом.
    registration_id = db.Column(
        db.BigInteger,
        db.ForeignKey('event_registrations.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    enrollment_id = db.Column(
        db.BigInteger,
        db.ForeignKey('online_enrollments.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    payment_id = db.Column(db.String(255))
    order_id = db.Column(db.String(100), nullable=False, index=True)
    liqpay_status = db.Column(db.String(50))
    mapped_status = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Numeric(10, 2))
    raw_payload = db.Column(db.JSON)
    source = db.Column(db.String(20), nullable=False)

    __table_args__ = (
        db.Index(
            'ix_payment_transactions_reg_created',
            'registration_id', 'created_at',
        ),
        db.CheckConstraint(
            "source IN ('callback', 'status_check', 'refund', 'manual')",
            name='ck_payment_transactions_source',
        ),
        db.CheckConstraint(
            "mapped_status IN ('unpaid', 'pending', 'paid', 'refunded')",
            name='ck_payment_transactions_mapped_status',
        ),
        # Рядок без жодного власника -- сирота, якої не знайде жодна звірка;
        # рядок з обома -- операція, яку порахують двічі. Заборонено і те, і те.
        db.CheckConstraint(
            '(registration_id IS NULL) <> (enrollment_id IS NULL)',
            name='ck_payment_transactions_single_owner',
        ),
    )

    registration = db.relationship(
        'EventRegistration', backref=db.backref('payment_transactions', lazy='dynamic'),
    )
    enrollment = db.relationship(
        'OnlineEnrollment', backref=db.backref('payment_transactions', lazy='dynamic'),
    )

    SOURCES = [
        ('callback', 'LiqPay Callback'),
        ('status_check', 'Перевірка статусу'),
        ('refund', 'Повернення'),
        ('manual', 'Ручне оновлення'),
    ]

    @property
    def source_label(self):
        return dict(self.SOURCES).get(self.source, self.source)

    def __repr__(self):
        return (
            f'<PaymentTransaction {self.id} reg={self.registration_id} '
            f'{self.mapped_status} via {self.source}>'
        )
