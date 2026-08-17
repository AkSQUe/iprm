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
    __translatable__ = ('name', 'description', 'badge')

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

    # Прапорець над карткою тарифу ("З підтримкою після курсу"). Порожньо --
    # прапорця немає.
    badge = db.Column(db.String(60))
    # Виділена картка на сторінці курсу. Раніше "головним" був просто
    # останній тариф у списку (loop.last у шаблоні) -- порядок сортування
    # вирішував за маркетинг. Тепер це явний вибір адміна.
    is_featured = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.false(),
    )

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
        """Опис тарифу як список пунктів (по одному на рядок).

        Свідомо читає канонічну колонку, а не self.t(): єдині споживачі --
        адмінка й форма реєстрації, де потрібен український оригінал.
        Для публічної сторінки курсу є description_entries.
        """
        if not self.description:
            return []
        return [line.strip() for line in self.description.splitlines() if line.strip()]

    @property
    def description_entries(self):
        """Пункти тарифу для публічної сторінки: [{'text', 'is_plus'}].

        Рядок, що починається з "+", позначає перевагу цього тарифу над
        базовим і рендериться іншим маркером. Конвенція в тексті, а не
        окреме поле: адміну простіше дописати "+" у рядок, ніж вести
        паралельний список, і порядок пунктів лишається один.
        """
        raw = self.t('description') or ''
        entries = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            is_plus = line.startswith('+')
            entries.append({
                'text': line.lstrip('+').strip() if is_plus else line,
                'is_plus': is_plus,
            })
        return entries

    def __repr__(self):
        return f'<InstanceTariff {self.name} instance={self.instance_id} price={self.price}>'
