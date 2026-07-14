"""Реєстр реферальних нарахувань (Фаза 3).

Один рядок = одне нарахування за одну оплачену реєстрацію. Унікальність за
registration_id гарантує ідемпотентність (повторний виклик award не дублює).
Баланс реферера = SUM(points) активних (granted) нарахувань. При поверненні
коштів рядок переводиться у 'voided' (бали віднімаються з балансу).

Реферер поліморфний (User або Trainer), тому referrer_id -- не FK, а знімок
id + kind + код (для стабільної історії навіть після змін у каталозі).
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow


class ReferralReward(TimestampMixin, db.Model):
    __tablename__ = 'referral_rewards'

    id = db.Column(BigIntPK, primary_key=True)

    # Одне нарахування на реєстрацію (ідемпотентність через UNIQUE).
    registration_id = db.Column(
        db.BigInteger,
        db.ForeignKey('event_registrations.id', ondelete='CASCADE'),
        nullable=False, unique=True, index=True,
    )

    # Поліморфний реферер: 'user' (User) або 'trainer' (Trainer).
    referrer_kind = db.Column(db.String(10), nullable=False)
    referrer_id = db.Column(db.BigInteger, nullable=False)
    # Знімок коду реферера на момент нарахування.
    referral_code = db.Column(db.String(32), nullable=False)

    points = db.Column(db.Integer, nullable=False, default=0)
    # 'granted' -- активне нарахування; 'voided' -- анульоване (повернення коштів).
    status = db.Column(db.String(16), nullable=False, default='granted', index=True)
    voided_at = db.Column(db.DateTime(timezone=True))
    notes = db.Column(db.String(255))

    registration = db.relationship('EventRegistration')

    __table_args__ = (
        db.CheckConstraint(
            "referrer_kind IN ('user', 'trainer')",
            name='ck_referral_rewards_kind',
        ),
        db.CheckConstraint(
            "status IN ('granted', 'voided')",
            name='ck_referral_rewards_status',
        ),
        db.CheckConstraint('points >= 0', name='ck_referral_rewards_points_non_negative'),
        # Баланс реферера рахуємо по цьому індексу.
        db.Index('ix_referral_rewards_referrer', 'referrer_kind', 'referrer_id', 'status'),
    )

    STATUSES = [
        ('granted', 'Нараховано'),
        ('voided', 'Анульовано'),
    ]

    def void(self, reason=None):
        """Перевести нарахування в анульоване. Не комітить."""
        self.status = 'voided'
        self.voided_at = utcnow()
        if reason:
            self.notes = reason

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    def __repr__(self):
        return (f'<ReferralReward reg={self.registration_id} '
                f'{self.referrer_kind}:{self.referrer_id} {self.points}p {self.status}>')
