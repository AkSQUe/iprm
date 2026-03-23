from datetime import datetime, timezone
from app.extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class Event(db.Model):
    __tablename__ = 'events'

    id = db.Column(db.BigInteger, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    subtitle = db.Column(db.String(500))
    description = db.Column(db.Text)
    short_description = db.Column(db.String(500))
    event_type = db.Column(db.String(30))
    format = db.Column(db.String(20))
    status = db.Column(db.String(20), default='draft', index=True)
    start_date = db.Column(db.DateTime(timezone=True))
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
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=True)
    trainer_id = db.Column(db.BigInteger, db.ForeignKey('trainers.id'), nullable=True)

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
        return dict(self.FORMATS).get(self.format, self.format)

    def __repr__(self):
        return f'<Event {self.title}>'
