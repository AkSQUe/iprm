from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class EventRegistration(TimestampMixin, db.Model):
    __tablename__ = 'event_registrations'

    id = db.Column(BigIntPK, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)

    phone = db.Column(db.String(20), nullable=False)
    specialty = db.Column(db.String(200), nullable=False)
    workplace = db.Column(db.String(300), nullable=False)
    experience_years = db.Column(db.Integer)
    license_number = db.Column(db.String(50))

    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    payment_status = db.Column(db.String(20), default='unpaid', nullable=False, index=True)
    payment_amount = db.Column(db.Numeric(10, 2))
    payment_id = db.Column(db.String(255))
    paid_at = db.Column(db.DateTime(timezone=True))

    attended = db.Column(db.Boolean, default=False)
    cpd_points_awarded = db.Column(db.Integer)
    admin_notes = db.Column(db.Text)

    user = db.relationship('User', back_populates='registrations')
    event = db.relationship('Event', back_populates='registrations')
    email_logs = db.relationship('EmailLog', back_populates='registration')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'event_id', name='uq_user_event_registration'),
        db.Index('ix_registrations_event_status', 'event_id', 'status'),
        db.Index('ix_registrations_created_at', 'created_at'),
        db.CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled', 'completed')",
            name='ck_registrations_status',
        ),
        db.CheckConstraint(
            "payment_status IN ('unpaid', 'pending', 'paid', 'refunded')",
            name='ck_registrations_payment_status',
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

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def payment_status_label(self):
        return dict(self.PAYMENT_STATUSES).get(self.payment_status, self.payment_status)

    def __repr__(self):
        return f'<EventRegistration user={self.user_id} event={self.event_id}>'
