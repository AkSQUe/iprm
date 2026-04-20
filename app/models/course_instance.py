"""CourseInstance — конкретне проведення курсу (коли, де, формат).
Належить Course. Реєстрації прив'язуються до instance (не до Course).
"""
from sqlalchemy import func, select

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class CourseInstance(TimestampMixin, db.Model):
    __tablename__ = 'course_instances'

    id = db.Column(BigIntPK, primary_key=True)
    course_id = db.Column(
        db.BigInteger,
        db.ForeignKey('courses.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )

    start_date = db.Column(db.DateTime(timezone=True), index=True)
    end_date = db.Column(db.DateTime(timezone=True))

    event_format = db.Column(db.String(20))

    price = db.Column(db.Numeric(10, 2))
    cpd_points = db.Column(db.Integer)
    max_participants = db.Column(db.Integer)

    location = db.Column(db.String(255))
    online_link = db.Column(db.String(500))

    trainer_id = db.Column(
        db.BigInteger,
        db.ForeignKey('trainers.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    __table_args__ = (
        db.Index('ix_course_instances_course_status', 'course_id', 'status'),
        db.Index('ix_course_instances_start_date', 'start_date'),
        db.CheckConstraint(
            "event_format IN ('online', 'offline', 'hybrid')",
            name='ck_course_instances_event_format',
        ),
        db.CheckConstraint(
            "status IN ('draft', 'published', 'active', 'completed', 'cancelled')",
            name='ck_course_instances_status',
        ),
        db.CheckConstraint(
            'price >= 0 OR price IS NULL',
            name='ck_course_instances_price_non_negative',
        ),
        db.CheckConstraint(
            'cpd_points >= 0 OR cpd_points IS NULL',
            name='ck_course_instances_cpd_points_non_negative',
        ),
        db.CheckConstraint(
            'max_participants >= 1 OR max_participants IS NULL',
            name='ck_course_instances_max_participants_positive',
        ),
    )

    course = db.relationship('Course', back_populates='instances')
    trainer = db.relationship('Trainer', foreign_keys=[trainer_id])
    registrations = db.relationship(
        'EventRegistration',
        foreign_keys='EventRegistration.instance_id',
        back_populates='instance',
        lazy='dynamic',
    )

    FORMATS = [
        ('online', 'Онлайн'),
        ('offline', 'Офлайн'),
        ('hybrid', 'Гібрид'),
    ]

    STATUSES = [
        ('draft', 'Чернетка'),
        ('published', 'Опубліковано'),
        ('active', 'Активний'),
        ('completed', 'Завершено'),
        ('cancelled', 'Скасовано'),
    ]

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def format_label(self):
        return dict(self.FORMATS).get(self.event_format, self.event_format)

    @property
    def effective_price(self):
        return self.price if self.price is not None else (self.course.base_price if self.course else 0)

    @property
    def effective_cpd_points(self):
        return self.cpd_points if self.cpd_points is not None else (self.course.cpd_points if self.course else None)

    @property
    def effective_max_participants(self):
        if self.max_participants is not None:
            return self.max_participants
        return self.course.max_participants if self.course else None

    @property
    def effective_trainer(self):
        return self.trainer or (self.course.trainer if self.course else None)

    @property
    def registration_count(self):
        from app.models.registration import EventRegistration
        return self.registrations.filter(
            EventRegistration.status.notin_(['cancelled'])
        ).count()

    @property
    def has_capacity(self):
        cap = self.effective_max_participants
        if cap is None:
            return True
        return self.registration_count < cap

    @property
    def is_registration_open(self):
        return (
            self.status in ('published', 'active')
            and self.has_capacity
        )

    def __repr__(self):
        return f'<CourseInstance course={self.course_id} start={self.start_date}>'
