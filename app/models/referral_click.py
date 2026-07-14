"""Денний агрегат кліків по реферальних посиланнях (аналітика воронки).

Один рядок = (код, день) з лічильником. Не зберігаємо кожен клік окремо
(надто write-heavy) -- лише інкрементуємо денний агрегат. Дає воронку
"кліки -> реєстрації -> оплати" на реферера.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class ReferralClick(TimestampMixin, db.Model):
    __tablename__ = 'referral_clicks'

    id = db.Column(BigIntPK, primary_key=True)
    referral_code = db.Column(db.String(32), nullable=False, index=True)
    day = db.Column(db.Date, nullable=False)
    count = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint('referral_code', 'day', name='uq_referral_clicks_code_day'),
    )

    def __repr__(self):
        return f'<ReferralClick {self.referral_code} {self.day}={self.count}>'
