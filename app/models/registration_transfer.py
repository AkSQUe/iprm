"""RegistrationTransfer -- перенесення реєстрації на інше проведення.

Окрема таблиця, а не колонки на EventRegistration: людину можна переносити
повторно, і другий перенос не має затирати перший. Реєстрація вже несе
понад тридцять колонок -- дописувати туди ще вісім означало б, що кожен
лістинг тягне поля, потрібні одному екрану.

Суми тут -- ЗНІМКИ на момент переносу, як `quoted_*` у RefundRequest: тариф
можна відредагувати заднім числом, і жива формула дала б іншу відповідь,
ніж та, яку учасник побачив у листі.

Гроші звідси не рухаються. Рішення про повернення лишається за чергою
заявок і сторінкою /admin/refunds/..., доплата -- за LiqPay-callback у
payment_ops. Одне місце, де система віддає гроші, легше стерегти, ніж три.
"""
import secrets
from datetime import timedelta, timezone

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow

CONSENT_TOKEN_TTL_DAYS = 30

STATE_APPLIED = 'applied'
STATE_AWAITING = 'awaiting_consent'
STATE_ACCEPTED = 'accepted'
STATE_REFUND_REQUESTED = 'refund_requested'

INITIATOR_ORGANIZER = 'organizer'
INITIATOR_PARTICIPANT = 'participant'

DECISION_KEEP = 'keep'
DECISION_REFUND_DIFF = 'refund_diff'
DECISION_SURCHARGE = 'surcharge'


class RegistrationTransfer(TimestampMixin, db.Model):
    __tablename__ = 'registration_transfers'

    STATE_APPLIED = STATE_APPLIED
    STATE_AWAITING = STATE_AWAITING
    STATE_ACCEPTED = STATE_ACCEPTED
    STATE_REFUND_REQUESTED = STATE_REFUND_REQUESTED

    id = db.Column(BigIntPK, primary_key=True)
    registration_id = db.Column(
        db.BigInteger,
        db.ForeignKey('event_registrations.id', ondelete='CASCADE'),
        nullable=False,
    )
    # SET NULL, а не CASCADE: історія перенесення має пережити видалення
    # заходу, інакше зникає саме той запис, заради якого таблиця й заведена.
    from_instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='SET NULL'),
        nullable=True,
    )
    to_instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='SET NULL'),
        nullable=True,
    )

    initiator = db.Column(db.String(20), nullable=False)
    announced = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false(),
    )

    # Порожні поля НЕ рендеряться в листі -- ані заголовка, ані порожнього
    # блоку. Тому NULL тут значуще, і порожній рядок нормалізуємо в None.
    reason = db.Column(db.String(500))
    note = db.Column(db.Text)

    tariff_decision = db.Column(db.String(20), nullable=False)
    to_tariff_id = db.Column(
        db.BigInteger,
        db.ForeignKey('instance_tariffs.id', ondelete='SET NULL'),
        nullable=True,
    )

    old_amount = db.Column(db.Numeric(10, 2))
    new_amount = db.Column(db.Numeric(10, 2))
    difference = db.Column(db.Numeric(10, 2))

    state = db.Column(db.String(20), nullable=False, index=True)

    consent_token = db.Column(db.String(64), unique=True, index=True)
    consent_token_expires_at = db.Column(db.DateTime(timezone=True))
    responded_at = db.Column(db.DateTime(timezone=True))

    refund_request_id = db.Column(
        db.BigInteger,
        db.ForeignKey('refund_requests.id', ondelete='SET NULL'),
        nullable=True,
    )

    surcharge_paid_at = db.Column(db.DateTime(timezone=True))
    surcharge_payment_id = db.Column(db.String(255))

    created_by_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )

    registration = db.relationship('EventRegistration')
    from_instance = db.relationship(
        'CourseInstance', foreign_keys=[from_instance_id])
    to_instance = db.relationship(
        'CourseInstance', foreign_keys=[to_instance_id])
    to_tariff = db.relationship('InstanceTariff', foreign_keys=[to_tariff_id])
    refund_request = db.relationship('RefundRequest')
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    __table_args__ = (
        db.CheckConstraint(
            "state IN ('applied', 'awaiting_consent', 'accepted', "
            "'refund_requested')",
            name='ck_registration_transfers_state',
        ),
        db.CheckConstraint(
            "initiator IN ('organizer', 'participant')",
            name='ck_registration_transfers_initiator',
        ),
        db.CheckConstraint(
            "tariff_decision IN ('keep', 'refund_diff', 'surcharge')",
            name='ck_registration_transfers_decision',
        ),
        # §3.2 Політики: перенесення з ініціативи Організатора -- без
        # додаткової оплати. Правило стоїть у БД, бо родом з оферти.
        db.CheckConstraint(
            "NOT (initiator = 'organizer' AND tariff_decision = 'surcharge')",
            name='ck_registration_transfers_organizer_no_surcharge',
        ),
        # Одне відкрите перенесення на реєстрацію. Без цього повторний клік
        # адміна лишав би дві пропозиції, і згода закривала б випадкову.
        db.Index(
            'uq_registration_transfers_open',
            'registration_id', unique=True,
            postgresql_where=db.text("state = 'awaiting_consent'"),
            sqlite_where=db.text("state = 'awaiting_consent'"),
        ),
        db.Index('ix_registration_transfers_registration', 'registration_id'),
    )

    STATES = [
        (STATE_APPLIED, 'Виконано'),
        (STATE_AWAITING, 'Очікує відповіді'),
        (STATE_ACCEPTED, 'Погоджено учасником'),
        (STATE_REFUND_REQUESTED, 'Учасник просить повернення'),
    ]

    STATE_BADGES = {
        STATE_APPLIED: 'active',
        STATE_AWAITING: 'pending',
        STATE_ACCEPTED: 'active',
        STATE_REFUND_REQUESTED: 'cancelled',
    }

    INITIATORS = [
        (INITIATOR_ORGANIZER, 'З ініціативи Організатора'),
        (INITIATOR_PARTICIPANT, 'На прохання учасника'),
    ]

    DECISIONS = [
        (DECISION_KEEP, 'Лишити суму як є'),
        (DECISION_REFUND_DIFF, 'Повернути різницю'),
        (DECISION_SURCHARGE, 'Запросити доплату різниці'),
    ]

    @property
    def state_label(self):
        return dict(self.STATES).get(self.state, self.state)

    @property
    def state_badge(self):
        return self.STATE_BADGES.get(self.state, 'draft')

    @property
    def initiator_label(self):
        return dict(self.INITIATORS).get(self.initiator, self.initiator)

    @property
    def tariff_decision_label(self):
        return dict(self.DECISIONS).get(
            self.tariff_decision, self.tariff_decision)

    @property
    def surcharge_due(self):
        """Доплату запросили, але вона ще не надійшла."""
        return (self.tariff_decision == DECISION_SURCHARGE
                and self.surcharge_paid_at is None)

    @property
    def is_open(self):
        return self.state == STATE_AWAITING

    def issue_consent_token(self, ttl_days=CONSENT_TOKEN_TTL_DAYS):
        """Згенерувати токен публічного посилання. Не комітить."""
        self.consent_token = secrets.token_urlsafe(32)
        self.consent_token_expires_at = utcnow() + timedelta(days=ttl_days)
        return self.consent_token

    @property
    def consent_token_active(self):
        if not self.consent_token or self.consent_token_expires_at is None:
            return False
        exp = self.consent_token_expires_at
        if exp.tzinfo is None:  # SQLite повертає naive
            exp = exp.replace(tzinfo=timezone.utc)
        return utcnow() <= exp

    def __repr__(self):
        return (f'<RegistrationTransfer {self.id} REG-{self.registration_id} '
                f'{self.state}>')
