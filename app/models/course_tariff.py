"""CourseTariff — шаблонний тариф курсу (дефолтна тарифна вилка).

Схема copy-on-create: при створенні проведення активні шаблони курсу,
що відповідають формату проведення, КОПІЮЮТЬСЯ в instance_tariffs
(див. course_service.copy_course_tariffs_to_instance). Далі проведення
живе власними тарифами — джерело істини для продажу завжди
instance_tariffs; шаблони курсу на існуючі проведення не впливають.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, TranslatableMixin, BigIntPK


class CourseTariff(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'course_tariffs'
    __translatable__ = ('name', 'description')

    id = db.Column(BigIntPK, primary_key=True)
    course_id = db.Column(
        db.BigInteger,
        db.ForeignKey('courses.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )

    name = db.Column(db.String(100), nullable=False)
    # Що входить у тариф: один пункт на рядок.
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2), nullable=False)

    # Для яких форматів проведення призначений шаблон: 'online', 'offline'
    # або NULL (будь-який). Гібридне проведення отримує всі шаблони.
    event_format = db.Column(db.String(20))

    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.Index('ix_course_tariffs_course_sort', 'course_id', 'sort_order'),
        db.CheckConstraint('price >= 0', name='ck_course_tariffs_price_non_negative'),
        db.CheckConstraint(
            "event_format IN ('online', 'offline') OR event_format IS NULL",
            name='ck_course_tariffs_event_format',
        ),
    )

    course = db.relationship('Course', back_populates='default_tariffs')

    FORMAT_CHOICES = [
        ('', 'Будь-який формат'),
        ('online', 'Лише онлайн-проведення'),
        ('offline', 'Лише офлайн-проведення'),
    ]

    @property
    def format_label(self):
        return dict(self.FORMAT_CHOICES).get(self.event_format or '', 'Будь-який формат')

    @property
    def description_items(self):
        if not self.description:
            return []
        return [line.strip() for line in self.description.splitlines() if line.strip()]

    def matches_format(self, instance_format):
        """Чи призначений шаблон для проведення з даним форматом.

        NULL-шаблон пасує всім; гібрид отримує і онлайн-, і офлайн-шаблони.
        """
        if not self.event_format:
            return True
        if instance_format == 'hybrid':
            return True
        return self.event_format == instance_format

    def __repr__(self):
        return f'<CourseTariff {self.name} course={self.course_id} price={self.price}>'
