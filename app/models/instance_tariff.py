"""InstanceTariff — тариф (опція участі) конкретного проведення.

Тарифна вилка від економ до преміум (бачення Дмитра, 08.07.2026):
Онлайн (~1500) -> Онлайн+ (чат з тренером) -> Практикум (очно, 5-15 тис)
-> Практикум з менторством (+70%, супровід власного прийому). Ціни
вводяться вручну для кожного тарифу — автоматичне формування неможливе
(різні гонорари, зали, розхідники).

Коли у проведення є активні тарифи, його effective_price — мінімальний
тариф ("від N грн" у картках/графіку).
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, TranslatableMixin, BigIntPK


class InstanceTariff(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'instance_tariffs'
    __translatable__ = ('name', 'description')

    id = db.Column(BigIntPK, primary_key=True)
    instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )

    name = db.Column(db.String(100), nullable=False)
    # Що входить у тариф: один пункт на рядок (рендериться списком).
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2), nullable=False)

    # Як саме учасник бере участь за цим тарифом: 'online', 'offline' або
    # NULL (не вказано). Успадковується від шаблону курсу при копіюванні.
    #
    # Головне застосування -- гібридне проведення: там частина тарифів
    # онлайнові, частина очні, і підтвердження "я точно приїду" має сенс
    # лише для других. NULL трактуємо консервативно -- як очну участь, бо
    # зайве попередження нешкідливе, а пропущене -- ні.
    event_format = db.Column(db.String(20))

    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.Index('ix_instance_tariffs_instance_sort', 'instance_id', 'sort_order'),
        db.CheckConstraint('price >= 0', name='ck_instance_tariffs_price_non_negative'),
        db.CheckConstraint(
            "event_format IN ('online', 'offline') OR event_format IS NULL",
            name='ck_instance_tariffs_event_format',
        ),
    )

    instance = db.relationship('CourseInstance', back_populates='tariffs')

    # Шаблонні назви вилки (підказка адміну; назва — довільний текст).
    PRESET_NAMES = [
        'Онлайн',
        'Онлайн+',
        'Практикум',
        'Практикум з менторством',
    ]

    FORMAT_CHOICES = [
        ('', 'Не вказано (вважається очною)'),
        ('online', 'Онлайн-участь'),
        ('offline', 'Очна участь'),
    ]

    @property
    def format_label(self):
        return dict(self.FORMAT_CHOICES).get(self.event_format or '', 'Не вказано')

    @property
    def requires_presence(self):
        """Чи потребує цей тариф фізичної присутності.

        NULL -- так: пропущене попередження про поїздку дорожче за зайве.
        """
        return self.event_format != 'online'

    @property
    def description_items(self):
        """Опис тарифу як список пунктів (по одному на рядок)."""
        if not self.description:
            return []
        return [line.strip() for line in self.description.splitlines() if line.strip()]

    def __repr__(self):
        return f'<InstanceTariff {self.name} instance={self.instance_id} price={self.price}>'
