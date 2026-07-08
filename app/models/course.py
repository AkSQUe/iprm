"""Course — каталожна сутність. Описує продукт (що за курс),
не має дати. Проведення (CourseInstance) прив'язуються до Course.
"""
from datetime import datetime, timezone

from sqlalchemy import func

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class Course(TimestampMixin, db.Model):
    __tablename__ = 'courses'

    id = db.Column(BigIntPK, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    subtitle = db.Column(db.String(500))

    description = db.Column(db.Text)
    short_description = db.Column(db.String(500))

    event_type = db.Column(db.String(30))

    # Зображення -- лише через медіа-реєстр (Фаза 6: legacy hero/card_image прибрано).
    hero_media_id = db.Column(
        db.BigInteger, db.ForeignKey('media_files.id', ondelete='SET NULL'), nullable=True,
    )
    card_media_id = db.Column(
        db.BigInteger, db.ForeignKey('media_files.id', ondelete='SET NULL'), nullable=True,
    )

    target_audience = db.Column(db.JSON, default=list)
    tags = db.Column(db.JSON, default=list)
    speaker_info = db.Column(db.Text)
    agenda = db.Column(db.Text)
    faq = db.Column(db.JSON, default=list)

    base_price = db.Column(db.Numeric(10, 2), default=0)
    cpd_points = db.Column(db.Integer)
    max_participants = db.Column(db.Integer)
    # Рівень складності 1..3 (базовий/просунутий/експертний); NULL -- не вказано.
    difficulty_level = db.Column(db.Integer)
    # Реєстраційний номер заходу БПР (7 цифр) -- сегмент номера сертифіката.
    bpr_event_number = db.Column(db.String(20))
    # Спеціальності заходу БПР для сертифіката (напр. "усі лікарські спеціальності").
    bpr_specialties = db.Column(db.String(500))
    # Бали БПР, що нараховуються ЛЕКТОРУ заходу (відрізняються від балів
    # учасника) -- для лекторського сертифіката.
    bpr_lecturer_points = db.Column(db.Integer)

    trainer_id = db.Column(
        db.BigInteger,
        db.ForeignKey('trainers.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    created_by = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    is_active = db.Column(db.Boolean, default=True, index=True)
    is_featured = db.Column(db.Boolean, default=False)

    # Кастомний порядок каталогу: закріплені курси першими, далі за
    # sort_order (зростання), потім за назвою. Керується з адмінки.
    is_pinned = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    __table_args__ = (
        db.Index('ix_courses_active_featured', 'is_active', 'is_featured'),
        db.Index('ix_courses_created_at', 'created_at'),
        db.CheckConstraint(
            "event_type IN ('seminar', 'webinar', 'course', 'masterclass', 'conference')",
            name='ck_courses_event_type',
        ),
        db.CheckConstraint('base_price >= 0', name='ck_courses_base_price_non_negative'),
        db.CheckConstraint(
            'cpd_points >= 0 OR cpd_points IS NULL',
            name='ck_courses_cpd_points_non_negative',
        ),
        db.CheckConstraint(
            'max_participants >= 1 OR max_participants IS NULL',
            name='ck_courses_max_participants_positive',
        ),
    )

    trainer = db.relationship(
        'Trainer', foreign_keys=[trainer_id], back_populates='courses',
    )
    creator = db.relationship(
        'User', foreign_keys=[created_by], back_populates='created_courses',
    )
    instances = db.relationship(
        'CourseInstance',
        back_populates='course',
        order_by='CourseInstance.start_date',
        cascade='all, delete-orphan',
    )
    program_blocks = db.relationship(
        'ProgramBlock',
        back_populates='course',
        order_by='ProgramBlock.sort_order',
        cascade='all, delete-orphan',
    )
    requests = db.relationship(
        'CourseRequest',
        back_populates='course',
        cascade='all, delete-orphan',
    )
    hero_media = db.relationship('MediaFile', foreign_keys=[hero_media_id])
    card_media = db.relationship('MediaFile', foreign_keys=[card_media_id])

    @property
    def hero_src(self):
        """URL hero для <img src> (повний варіант). None, якщо немає."""
        return self.hero_media.url if self.hero_media else None

    @property
    def card_src(self):
        """URL картки/прев'ю (card-варіант). None, якщо немає."""
        return self.card_media.variant_url('card') if self.card_media else None

    EVENT_TYPES = [
        ('seminar', 'Семінар'),
        ('webinar', 'Вебінар'),
        ('course', 'Курс'),
        ('masterclass', 'Майстер-клас'),
        ('conference', 'Конференція'),
    ]

    DIFFICULTY_LEVELS = [
        (1, 'Рівень 1 — базовий'),
        (2, 'Рівень 2 — просунутий'),
        (3, 'Рівень 3 — експертний'),
    ]

    @property
    def event_type_label(self):
        return dict(self.EVENT_TYPES).get(self.event_type, self.event_type)

    @property
    def difficulty_label(self):
        return dict(self.DIFFICULTY_LEVELS).get(self.difficulty_level)

    @property
    def upcoming_instances(self):
        now = datetime.now(timezone.utc)
        return [
            i for i in self.instances
            if i.status in ('published', 'active')
            and (i.start_date is None or i.start_date >= now)
        ]

    @property
    def has_upcoming(self):
        return len(self.upcoming_instances) > 0

    @property
    def pending_requests_count(self):
        from app.models.course_request import CourseRequest
        return (
            db.session.query(func.count(CourseRequest.id))
            .filter(
                CourseRequest.course_id == self.id,
                CourseRequest.status == 'pending',
            )
            .scalar()
        )

    def __repr__(self):
        return f'<Course {self.title}>'
