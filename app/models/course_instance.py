"""CourseInstance — конкретне проведення курсу (коли, де, формат).
Належить Course. Реєстрації прив'язуються до instance (не до Course).
"""
import logging

from sqlalchemy import func, select

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK

logger = logging.getLogger(__name__)


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

    # start_date має index=True на колонці -- окремого ix_course_instances_start_date не додаємо.
    __table_args__ = (
        db.Index('ix_course_instances_course_status', 'course_id', 'status'),
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

    # `completed` — фінальний; історію завершених проведень не переписуємо.
    STATUS_TRANSITIONS = {
        'draft': {'published', 'active', 'cancelled'},
        'published': {'draft', 'active', 'completed', 'cancelled'},
        'active': {'published', 'completed', 'cancelled'},
        'completed': set(),
        'cancelled': {'draft', 'published'},
    }

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    def can_transition_to(self, new_status):
        """Перевірити чи дозволено перейти з поточного у new_status.

        Caller повинен окремо обробити випадок new_status == self.status
        (no-op, не вимагає дозволеного переходу).
        """
        return new_status in self.STATUS_TRANSITIONS.get(self.status, set())

    @property
    def format_label(self):
        return dict(self.FORMATS).get(self.event_format, self.event_format)

    def _warn_orphan(self, context):
        """Логувати якщо instance без course (дата-інтегріті issue)."""
        logger.warning(
            'CourseInstance id=%s course_id=%s has no course loaded (effective_%s fallback)',
            self.id, self.course_id, context,
        )

    @property
    def effective_price(self):
        if self.price is not None:
            return self.price
        if self.course is None:
            self._warn_orphan('price')
            return 0
        return self.course.base_price

    @property
    def effective_cpd_points(self):
        if self.cpd_points is not None:
            return self.cpd_points
        if self.course is None:
            self._warn_orphan('cpd_points')
            return None
        return self.course.cpd_points

    @property
    def effective_max_participants(self):
        if self.max_participants is not None:
            return self.max_participants
        if self.course is None:
            self._warn_orphan('max_participants')
            return None
        return self.course.max_participants

    @property
    def effective_trainer(self):
        if self.trainer is not None:
            return self.trainer
        if self.course is None:
            self._warn_orphan('trainer')
            return None
        return self.course.trainer

    @property
    def registration_count(self):
        """Кількість активних реєстрацій.

        Віддає кеш `_cached_reg_count` якщо попередньо встановлений caller-ом
        (batch COUNT у list-route-ах, щоб уникнути N+1). Інакше -- окремий
        COUNT-запит.
        """
        cached = getattr(self, '_cached_reg_count', None)
        if cached is not None:
            return cached
        from app.models.registration import EventRegistration
        return self.registrations.filter(
            EventRegistration.status.notin_(['cancelled'])
        ).count()

    @classmethod
    def with_registration_count(cls):
        """Subquery, що рахує активні реєстрації. Використовувати так:

        reg_count = CourseInstance.with_registration_count()
        db.session.query(CourseInstance, reg_count).all()
        """
        from app.models.registration import EventRegistration
        return (
            select(func.count(EventRegistration.id))
            .where(
                EventRegistration.instance_id == cls.id,
                EventRegistration.status.notin_(['cancelled']),
            )
            .correlate(cls)
            .scalar_subquery()
            .label('_registration_count')
        )

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
