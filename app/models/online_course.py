"""OnlineCourse -- онлайн-курс, що фізично живе в Sintegrum.

Це ДЗЕРКАЛО чужого каталогу плюс наші власні дані про продаж. Два набори
полів навмисно розділені:

* remote_* -- те, що приходить із Sintegrum. Їх перезаписує синхронізація,
  в адмінці вони лише для читання;
* решта -- наше: slug, тексти, ціна, зображення, посилання на навчання,
  публікація. Синхронізація їх не чіпає ніколи, інакше кожен прогін
  затирав би редакторську роботу.

Не плутати з Course: той описує офлайн-захід із проведеннями, датами,
містами, тарифами й сертифікатами БПР. Тут нічого цього немає, зате є
sintegrum_id і стан синхронізації.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, TranslatableMixin, BigIntPK


# Статуси курсу на боці Sintegrum (див. docs/integrations/sintegrum-api.md).
REMOTE_STATUS_INACTIVE = 0
REMOTE_STATUS_ACTIVE = 1
REMOTE_STATUS_ARCHIVED = 2

REMOTE_STATUS_LABELS = {
    REMOTE_STATUS_INACTIVE: 'Неактивний',
    REMOTE_STATUS_ACTIVE: 'Активний',
    REMOTE_STATUS_ARCHIVED: 'В архіві',
}


class OnlineCourse(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'online_courses'
    __translatable__ = ('title', 'description', 'short_description')

    id = db.Column(BigIntPK, primary_key=True)

    # ---- дані Sintegrum (пише лише синхронізація) ----
    sintegrum_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    remote_name = db.Column(db.String(255), nullable=False)
    remote_description = db.Column(db.Text)
    remote_price = db.Column(db.Numeric(10, 2))
    remote_status = db.Column(db.Integer)
    remote_parent_id = db.Column(db.Integer)
    # Сирий об'єкт останнього прогону. Sintegrum не версіонує API жорстко,
    # тож нові поля не мають губитись лише через те, що ми про них не знали.
    remote_payload = db.Column(db.JSON)

    first_seen_at = db.Column(db.DateTime(timezone=True))
    last_seen_at = db.Column(db.DateTime(timezone=True), index=True)
    # Курс зник із видачі Sintegrum. НЕ видаляємо: на нього можуть
    # посилатися вже оплачені замовлення.
    is_vanished = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.false(),
    )

    # ---- наші дані ----
    slug = db.Column(db.String(200), unique=True, nullable=False)
    # Перевизначення назви й описів. Порожньо -- показуємо дані Sintegrum.
    title = db.Column(db.String(255))
    description = db.Column(db.Text)
    short_description = db.Column(db.String(500))

    # Ціна продажу -- НАША (рішення Q3). remote_price лишається довідковим
    # і в замовлення не потрапляє ніколи.
    price = db.Column(db.Numeric(10, 2))
    currency = db.Column(
        db.String(3), default='UAH', server_default='UAH', nullable=False,
    )
    duration_hours = db.Column(db.Integer)
    # Довідкове поле. Видача сертифікатів за онлайн-курс -- окрема фаза (Q6).
    cpd_points = db.Column(db.Integer)

    is_published = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.false(),
    )
    is_featured = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.false(),
    )
    sort_order = db.Column(db.Integer, default=0, nullable=False, server_default='0')

    hero_media_id = db.Column(
        db.BigInteger, db.ForeignKey('media_files.id', ondelete='SET NULL'), nullable=True,
    )
    card_media_id = db.Column(
        db.BigInteger, db.ForeignKey('media_files.id', ondelete='SET NULL'), nullable=True,
    )

    # Ціль редіректу: посилання реєстрації на трек, згенероване в кабінеті
    # Sintegrum. Спільне для всіх і безстрокове, тому назовні не показується
    # ніде -- ані в шаблонах, ані в партнерському API. Учасник отримує наше
    # посилання з токеном, яке веде сюди.
    access_url = db.Column(db.String(1000))
    # Термін життя виданого токена. Порожньо -- беремо з налаштувань сайту.
    access_ttl_hours = db.Column(db.Integer)

    __table_args__ = (
        db.Index('ix_online_courses_published_sort', 'is_published', 'sort_order'),
        db.CheckConstraint('price >= 0 OR price IS NULL',
                           name='ck_online_courses_price_non_negative'),
        db.CheckConstraint('duration_hours > 0 OR duration_hours IS NULL',
                           name='ck_online_courses_duration_positive'),
        db.CheckConstraint('access_ttl_hours > 0 OR access_ttl_hours IS NULL',
                           name='ck_online_courses_ttl_positive'),
    )

    hero_media = db.relationship('MediaFile', foreign_keys=[hero_media_id])
    card_media = db.relationship('MediaFile', foreign_keys=[card_media_id])

    # ---- ефективні значення (наше перекриває чуже) ----

    @property
    def effective_title(self):
        return self.t('title') or self.remote_name

    @property
    def effective_description(self):
        return self.t('description') or self.remote_description or ''

    @property
    def effective_short_description(self):
        return self.t('short_description') or ''

    @property
    def hero_src(self):
        return self.hero_media.url if self.hero_media else None

    @property
    def card_src(self):
        return self.card_media.variant_url('card') if self.card_media else None

    @property
    def remote_status_label(self):
        return REMOTE_STATUS_LABELS.get(self.remote_status, 'Невідомо')

    @property
    def is_remote_active(self):
        return self.remote_status == REMOTE_STATUS_ACTIVE

    # ---- готовність до продажу ----

    @property
    def missing_for_publication(self):
        """Чого бракує, щоб курс можна було опублікувати.

        Повертає список причин, а не просто False: адмін має бачити, що саме
        доробити, а не гадати, чому перемикач не спрацював.
        """
        missing = []
        if not (self.access_url or '').strip():
            missing.append('посилання на навчання')
        if self.price is None or self.price <= 0:
            missing.append('ціна')
        if self.is_vanished:
            missing.append('курс зник із Sintegrum')
        return missing

    @property
    def can_be_published(self):
        return not self.missing_for_publication

    @property
    def is_purchasable(self):
        """Чи можна купити просто зараз (публічна сторона)."""
        return self.is_published and self.can_be_published

    def __repr__(self):
        return f'<OnlineCourse {self.sintegrum_id} {self.remote_name!r}>'
