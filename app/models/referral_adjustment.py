"""Ручні корекції балансу реферала (append-only леджер).

Окрема від ReferralReward сутність: ReferralReward -- це нарахування за
конкретну реєстрацію (earn/void), а ReferralAdjustment -- будь-яка ручна
зміна балансу оператором (+/- балів) із причиною й автором. Баланс реферера =
SUM(активних rewards) + SUM(adjustments).

Це фундамент під майбутню витрату балів (redemption -- окрема фаза, TODO):
списання оформлятиметься негативними записами тут або окремим типом.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class ReferralAdjustment(TimestampMixin, db.Model):
    __tablename__ = 'referral_adjustments'

    id = db.Column(BigIntPK, primary_key=True)

    # Поліморфний реферер (як у ReferralReward): 'user' | 'trainer'.
    referrer_kind = db.Column(db.String(10), nullable=False)
    referrer_id = db.Column(db.BigInteger, nullable=False)

    # Знакова величина: додатна -- нарахувати, відʼємна -- зняти.
    points = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    # Хто зробив корекцію (адмін). NULL -- системна (напр. згорання).
    created_by_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True,
    )

    created_by = db.relationship('User', foreign_keys=[created_by_id])

    __table_args__ = (
        db.CheckConstraint(
            "referrer_kind IN ('user', 'trainer')",
            name='ck_referral_adjustments_kind',
        ),
        db.Index('ix_referral_adjustments_referrer', 'referrer_kind', 'referrer_id'),
    )

    def __repr__(self):
        return (f'<ReferralAdjustment {self.referrer_kind}:{self.referrer_id} '
                f'{self.points:+d}>')
