from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class Event(TimestampMixin, db.Model):
    __tablename__ = 'events'

    id = db.Column(BigIntPK, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    subtitle = db.Column(db.String(500))
    description = db.Column(db.Text)
    short_description = db.Column(db.String(500))
    event_type = db.Column(db.String(30))
    event_format = db.Column(db.String(20))
    status = db.Column(db.String(20), default='draft', index=True)
    start_date = db.Column(db.DateTime(timezone=True), index=True)
    end_date = db.Column(db.DateTime(timezone=True))
    max_participants = db.Column(db.Integer)
    price = db.Column(db.Numeric(10, 2), default=0)
    location = db.Column(db.String(255))
    online_link = db.Column(db.String(500))
    hero_image = db.Column(db.String(500))
    card_image = db.Column(db.String(500))
    cpd_points = db.Column(db.Integer)
    target_audience = db.Column(db.JSON, default=list)
    tags = db.Column(db.JSON, default=list)
    speaker_info = db.Column(db.Text)
    agenda = db.Column(db.Text)
    is_featured = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_by = db.Column(db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    trainer_id = db.Column(db.BigInteger, db.ForeignKey('trainers.id', ondelete='SET NULL'), nullable=True, index=True)

    __table_args__ = (
        db.Index('ix_events_active_status', 'is_active', 'status'),
        db.CheckConstraint(
            "event_type IN ('seminar', 'webinar', 'course', 'masterclass', 'conference')",
            name='ck_events_event_type',
        ),
        db.CheckConstraint(
            "event_format IN ('online', 'offline', 'hybrid')",
            name='ck_events_event_format',
        ),
        db.CheckConstraint(
            "status IN ('draft', 'published', 'active', 'completed', 'cancelled')",
            name='ck_events_status',
        ),
    )

    creator = db.relationship('User', foreign_keys=[created_by])
    trainer = db.relationship('Trainer', back_populates='events')
    program_blocks = db.relationship(
        'ProgramBlock',
        back_populates='event',
        order_by='ProgramBlock.sort_order',
        cascade='all, delete-orphan',
    )

    EVENT_TYPES = [
        ('seminar', 'Семінар'),
        ('webinar', 'Вебінар'),
        ('course', 'Курс'),
        ('masterclass', 'Майстер-клас'),
        ('conference', 'Конференція'),
    ]

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
    def event_type_label(self):
        return dict(self.EVENT_TYPES).get(self.event_type, self.event_type)

    @property
    def format_label(self):
        return dict(self.FORMATS).get(self.event_format, self.event_format)

    @property
    def registration_count(self):
        from app.models.registration import EventRegistration
        return self.registrations.filter(
            EventRegistration.status.notin_(['cancelled'])
        ).count()

    @property
    def has_capacity(self):
        if self.max_participants is None:
            return True
        return self.registration_count < self.max_participants

    @property
    def is_registration_open(self):
        return (self.is_active
                and self.status in ('published', 'active')
                and self.has_capacity)

    def __repr__(self):
        return f'<Event {self.title}>'
