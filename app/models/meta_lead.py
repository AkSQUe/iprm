"""Ліди з Meta Lead Ads: сира черга подій + розібраний лід.

Дві таблиці, а не одна, бо в них різні строки життя і різна довіра до вмісту.

`meta_lead_events` -- те, що прийшло вебхуком або знайшлось звіркою. Вебхук
Meta приносить ЛИШЕ ідентифікатор ліда, не самі дані, тож рядок тут -- це
"треба сходити в Graph API". Payload не редагується і не видаляється: якщо
розбір виявиться помилковим, переграти можна лише з оригіналу.

`meta_leads` -- результат розбору: нормалізовані поля, зв'язок з контактом,
джерело (кампанія/форма/оголошення) і стан обробки менеджером.

Ідемпотентність тримається на `leadgen_id`, унікальному в ОБОХ таблицях.
Meta повторює доставку вебхука при будь-якому сумніві (таймаут, 5xx, а
подеколи й після успішної відповіді), а звірка навмисно перечитує ті самі
48 годин -- без цієї унікальності кожен такий повтор давав би дубль картки.
"""
from datetime import datetime, timezone

from app.extensions import db
from app.models.mixins import TimestampMixin, SoftDeleteMixin, BigIntPK
from app.utils import ensure_utc


# Скільки разів пробуємо забрати лід із Graph API, перш ніж визнати подію
# невдалою. П'ять спроб із backoff 1/2/4/8/16 хв -- те саме вікно, що в
# черзі партнерських вебхуків: переживає рестарт застосунку й короткий
# збій Graph API, але не крутиться добу на протухлому токені.
MAX_EVENT_ATTEMPTS = 5
EVENT_INITIAL_BACKOFF_SECONDS = 60


class MetaLeadEvent(TimestampMixin, db.Model):
    """Сира подія leadgen. Не редагується (крім полів стану) і не видаляється."""

    __tablename__ = 'meta_lead_events'

    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_RETRYING = 'retrying'
    STATUS_SKIPPED = 'skipped'

    STATUSES = [
        (STATUS_PENDING, 'В обробці'),
        (STATUS_PROCESSING, 'Обробляється'),
        (STATUS_RETRYING, 'Повтор'),
        (STATUS_DONE, 'Оброблено'),
        (STATUS_SKIPPED, 'Дубль'),
        (STATUS_FAILED, 'Помилка'),
    ]

    SOURCE_WEBHOOK = 'webhook'
    SOURCE_RECONCILE = 'reconcile'
    SOURCE_MANUAL = 'manual'

    id = db.Column(BigIntPK, primary_key=True)

    # Ідентифікатори Meta -- рядки, а не числа: вони 64-бітні й іноді
    # віддаються з провідними нулями, тож int їх мовчки псує.
    leadgen_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    page_id = db.Column(db.String(64), index=True)
    form_id = db.Column(db.String(64), index=True)
    ad_id = db.Column(db.String(64))

    # Час створення ліда за версією Meta (не час прийому вебхука).
    created_time = db.Column(db.DateTime(timezone=True), index=True)
    received_at = db.Column(db.DateTime(timezone=True), nullable=False,
                            default=lambda: datetime.now(timezone.utc))

    # Повний `value` з changes[] (вебхук) або мінімальний dict зі звірки.
    # Саме він -- страховка на випадок помилок у логіці розбору.
    raw_payload = db.Column(db.JSON, nullable=False, default=dict)

    source = db.Column(
        db.String(20), nullable=False, default=SOURCE_WEBHOOK,
        server_default=SOURCE_WEBHOOK, index=True,
    )
    status = db.Column(
        db.String(20), nullable=False, default=STATUS_PENDING,
        server_default=STATUS_PENDING, index=True,
    )
    attempts = db.Column(
        db.Integer, nullable=False, default=0, server_default='0',
    )
    last_error = db.Column(db.Text)
    next_retry_at = db.Column(db.DateTime(timezone=True), index=True)
    processed_at = db.Column(db.DateTime(timezone=True))

    lead_id = db.Column(
        db.BigInteger, db.ForeignKey('meta_leads.id', ondelete='SET NULL'), index=True,
    )
    lead = db.relationship('MetaLead', back_populates='events', foreign_keys=[lead_id])

    __table_args__ = (
        db.Index('ix_meta_lead_events_status_retry', 'status', 'next_retry_at'),
        db.CheckConstraint(
            "status IN ('pending', 'processing', 'retrying', 'done', 'skipped', 'failed')",
            name='ck_meta_lead_events_status',
        ),
        db.CheckConstraint(
            "source IN ('webhook', 'reconcile', 'manual')",
            name='ck_meta_lead_events_source',
        ),
        db.CheckConstraint('attempts >= 0', name='ck_meta_lead_events_attempts'),
    )

    # Модифікатор `.badge--*` на кожен стан обробки. Раніше жив словником у
    # роуті; `retrying` і `failed` там указували на модифікатори, яких у
    # системі немає -- вони існували лише в page-admin-webhooks.css, а сторінки
    # лідів того файлу не підключають, тож «Повтор» і «Помилка» виходили
    # плашками без тла.
    STATUS_BADGES = {
        STATUS_PENDING: 'pending',
        STATUS_PROCESSING: 'pending',
        STATUS_RETRYING: 'warning',
        STATUS_DONE: 'active',
        STATUS_SKIPPED: 'draft',
        STATUS_FAILED: 'cancelled',
    }

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def status_badge(self):
        """Модифікатор `.badge--*` під поточний стан (див. STATUS_BADGES)."""
        return self.STATUS_BADGES.get(self.status, 'draft')

    @property
    def is_terminal(self):
        return self.status in (self.STATUS_DONE, self.STATUS_FAILED, self.STATUS_SKIPPED)

    def __repr__(self):
        return (
            f'<MetaLeadEvent id={self.id} leadgen_id={self.leadgen_id} '
            f'status={self.status} attempts={self.attempts}>'
        )


class MetaLead(TimestampMixin, SoftDeleteMixin, db.Model):
    """Розібрана заявка з інстант-форми Meta, прив'язана до контакту.

    М'яке видалення (`SoftDeleteMixin`) -- через тестові ліди: інструмент
    Lead Ads Testing Tool ллє заявки тим самим шляхом, що й реальні, і
    прибирати їх треба, не втрачаючи можливості скасувати помилковий клік.
    Сира подія при цьому НЕ видаляється ніколи -- саме вона й тримає
    ідемпотентність, тож повторна доставка не воскресить видалену заявку.
    """

    __tablename__ = 'meta_leads'

    STATUS_NEW = 'new'
    STATUS_IN_WORK = 'in_work'
    STATUS_CLOSED = 'closed'
    STATUS_DISMISSED = 'dismissed'

    STATUSES = [
        (STATUS_NEW, 'Новий'),
        (STATUS_IN_WORK, 'У роботі'),
        (STATUS_CLOSED, 'Закрито'),
        (STATUS_DISMISSED, 'Відхилено'),
    ]

    # Як саме знайшовся контакт. Видно менеджеру: "створено" і "за поштою"
    # мають різну ціну помилки, і розбирати їх треба по-різному.
    MATCH_PHONE = 'phone'
    MATCH_EMAIL = 'email'
    MATCH_CREATED = 'created'
    MATCH_NONE = 'none'

    MATCH_METHODS = [
        (MATCH_PHONE, 'За телефоном'),
        (MATCH_EMAIL, 'За поштою'),
        (MATCH_CREATED, 'Створено контакт'),
        (MATCH_NONE, 'Без контакту'),
    ]

    id = db.Column(BigIntPK, primary_key=True)

    leadgen_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    # Час подання заявки людиною. Від нього рахується час очікування, тому
    # він nullable=False: лід без нього неможливо пріоритезувати.
    created_time = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    page_id = db.Column(db.String(64))
    form_id = db.Column(db.String(64), index=True)
    form_name = db.Column(db.String(255))
    campaign_id = db.Column(db.String(64), index=True)
    campaign_name = db.Column(db.String(255))
    adset_id = db.Column(db.String(64))
    adset_name = db.Column(db.String(255))
    ad_id = db.Column(db.String(64))
    ad_name = db.Column(db.String(255))
    platform = db.Column(db.String(10))
    is_organic = db.Column(
        db.Boolean, default=False, server_default=db.false(), nullable=False,
    )

    # Усі відповіді як їх віддала Meta: {name: value}. Набір питань у формах
    # змінюється щокампанії, тож окремі колонки під кожне питання застаріли б
    # раніше, ніж доїхала б міграція.
    field_data = db.Column(db.JSON, nullable=False, default=dict)
    # Повна відповідь Graph API -- для розбору, коли нормалізація помилилась.
    raw_lead = db.Column(db.JSON)

    first_name = db.Column(db.String(120))
    last_name = db.Column(db.String(120))
    full_name = db.Column(db.String(255))
    email = db.Column(db.String(255), index=True)
    phone_raw = db.Column(db.String(50))
    # Канонічна форма для зіставлення. NULL = номер не розпізнано; такий лід
    # шукає контакт лише за поштою -- вигадувати за людину номер не можна.
    phone_e164 = db.Column(db.String(16), index=True)

    user_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'), index=True,
    )
    match_method = db.Column(
        db.String(20), nullable=False, default=MATCH_NONE,
        server_default=MATCH_NONE,
    )

    # Ручний розбір. Автоматичне злиття контактів заборонене: якщо телефон
    # веде на один контакт, а пошта -- на інший, рішення приймає людина.
    needs_attention = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false(),
        index=True,
    )
    attention_reason = db.Column(db.Text)
    conflict_user_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
    )
    # Пошта, що прийшла з лідом при збігу за телефоном і НЕ збіглася з
    # основною поштою контакту. Не перезаписує users.email (це логін і
    # унікальний ключ) -- лежить тут і показується менеджеру.
    alt_email = db.Column(db.String(255))

    # Повторне звернення: контакт уже мав лід із Meta до цього.
    is_repeat = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false(),
        index=True,
    )

    # Тестова заявка (Lead Ads Testing Tool). Graph API надійного прапорця
    # не віддає, тож ставимо його самі: усе, що прийшло при увімкненому
    # «режимі тестування» в адмінці, плюс ручна позначка. У списку такі
    # заявки сховані, у партнерську чергу не потрапляють.
    is_test = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false(),
        index=True,
    )

    status = db.Column(
        db.String(20), nullable=False, default=STATUS_NEW,
        server_default=STATUS_NEW, index=True,
    )
    admin_notes = db.Column(db.Text)
    # Коли менеджер уперше взяв лід у роботу. Разом із created_time дає
    # реальний час першої реакції -- саме він, а не кількість лідів,
    # визначає конверсію.
    first_touch_at = db.Column(db.DateTime(timezone=True))
    first_touch_by = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
    )

    user = db.relationship('User', foreign_keys=[user_id])
    conflict_user = db.relationship('User', foreign_keys=[conflict_user_id])
    toucher = db.relationship('User', foreign_keys=[first_touch_by])
    events = db.relationship(
        'MetaLeadEvent', back_populates='lead', foreign_keys=[MetaLeadEvent.lead_id],
    )

    __table_args__ = (
        db.Index('ix_meta_leads_status_created', 'status', 'created_time'),
        # Два часткові індекси під зрізи, які реєстр виконує на кожен рендер:
        # типовий порядок (найновіші живі нетестові) і порядок «спершу без
        # реакції». Часткові -- бо видалені й тестові заявки в реєстрі не
        # показуються ніколи, тож у індексі їм робити нічого.
        db.Index(
            'ix_meta_leads_active_created', db.text('created_time DESC'),
            postgresql_where=db.text('deleted_at IS NULL AND is_test = false'),
        ),
        db.Index(
            'ix_meta_leads_active_wait',
            db.text('(first_touch_at IS NULL) DESC'),
            db.text('created_time ASC'),
            postgresql_where=db.text('deleted_at IS NULL AND is_test = false'),
        ),
        db.CheckConstraint(
            "status IN ('new', 'in_work', 'closed', 'dismissed')",
            name='ck_meta_leads_status',
        ),
        db.CheckConstraint(
            "match_method IN ('phone', 'email', 'created', 'none')",
            name='ck_meta_leads_match_method',
        ),
    )

    # Модифікатор `.badge--*` на кожен стан заявки -- раніше словником у роуті.
    STATUS_BADGES = {
        STATUS_NEW: 'warning',
        STATUS_IN_WORK: 'pending',
        STATUS_CLOSED: 'active',
        STATUS_DISMISSED: 'draft',
    }

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def status_badge(self):
        """Модифікатор `.badge--*` під поточний стан (див. STATUS_BADGES)."""
        return self.STATUS_BADGES.get(self.status, 'draft')

    @property
    def match_label(self):
        return dict(self.MATCH_METHODS).get(self.match_method, self.match_method)

    @property
    def platform_label(self):
        return {'fb': 'Facebook', 'ig': 'Instagram'}.get(
            self.platform, self.platform or '–')

    @property
    def display_name(self):
        parts = ' '.join(p for p in (self.last_name, self.first_name) if p).strip()
        return parts or self.full_name or self.email or self.phone_raw or f'Лід #{self.id}'

    @property
    def source_label(self):
        """Звідки прийшов лід -- одним рядком для списку."""
        return ' / '.join(
            p for p in (self.campaign_name, self.form_name) if p
        ) or (self.form_id or '–')

    @property
    def waiting_seconds(self):
        """Скільки лід чекає першої реакції (сек). Після взяття в роботу --
        скільки чекав. Швидкість першого дзвінка -- головна метрика цієї
        сторінки, тому лічильник живе на моделі, а не в шаблоні."""
        if not self.created_time:
            return 0
        # `ensure_utc` замість ручної перевірки tzinfo: SQLite віддає ці
        # колонки наївними, і різниця з aware `now()` інакше падає TypeError.
        start = ensure_utc(self.created_time)
        end = ensure_utc(self.first_touch_at) or datetime.now(timezone.utc)
        return max(0, int((end - start).total_seconds()))

    @property
    def is_waiting(self):
        return self.first_touch_at is None and self.status == self.STATUS_NEW

    def __repr__(self):
        return (
            f'<MetaLead id={self.id} leadgen_id={self.leadgen_id} '
            f'user_id={self.user_id} status={self.status}>'
        )


class MetaLeadForm(TimestampMixin, db.Model):
    """Схема інстант-форми: людські підписи питань і варіантів відповіді.

    Існує рівно тому, що `field_data` ліда їх не містить. Для питання з
    варіантами Meta кладе у відповідь ліда внутрішній КЛЮЧ варіанта
    (`ортопедія_/_травматологія`), а не його текст; так само слугіфіковані
    й назви питань. Підпис живе лише у схемі форми, і забирається вона
    окремим полем `questions` Graph API.

    Схема НЕ вшивається в лід копією: підстановка робиться на показі, тож
    схема, яка приїхала пізніше за заявку, лагодить і вже наявні картки.
    `field_data` при цьому лишається дослівним -- він страховка на випадок
    помилки в самій підстановці.
    """

    __tablename__ = 'meta_lead_forms'

    id = db.Column(BigIntPK, primary_key=True)

    # Той самий тип, що й `MetaLead.form_id`: 64-бітні ідентифікатори Meta
    # int псує мовчки.
    form_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    page_id = db.Column(db.String(64), index=True)
    name = db.Column(db.String(255))
    status = db.Column(db.String(32))
    locale = db.Column(db.String(16))

    # `{ключ_питання: {'label': ..., 'type': ..., 'options': {ключ: підпис}}}`.
    # JSON, а не таблиця питань: набір питань змінюється щокампанії, а
    # читається схема цілком і завжди однією формою -- нормалізація дала б
    # тут лише зайвий JOIN на кожну картку ліда.
    questions = db.Column(db.JSON, nullable=False, default=dict)

    # Коли схему востаннє забрали з Graph API. Порожньо бути не може:
    # рядок і створюється лише як результат успішного походу.
    synced_at = db.Column(db.DateTime(timezone=True), nullable=False,
                          default=lambda: datetime.now(timezone.utc))

    # Захід, про який ця форма. Прив'язка руками в адмінці: Meta про наші
    # курси не знає нічого, а вгадувати захід із назви форми означало б
    # мовчки помилятись на другому потоці того самого курсу.
    #
    # SET NULL, а не CASCADE: видалення заходу не має забирати з собою
    # схему форми -- на ній тримаються підписи питань УСІХ уже наявних
    # заявок, і картка ліда без неї знову показувала б внутрішні ключі.
    course_instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='SET NULL'),
        index=True,
    )

    # `back_populates`, а не однобічний зв'язок: без зворотної колекції на
    # CourseInstance ORM не бачить, кому саме належить нулювати FK при
    # видаленні заходу, і в тестах (SQLite без увімкненого PRAGMA
    # foreign_keys) рядок форми лишається з посиланням на вже неіснуючий
    # запис. У проді той самий результат додатково гарантує сам FK
    # (ondelete='SET NULL') -- це підстраховка одне одного, не дублювання.
    course_instance = db.relationship('CourseInstance', back_populates='meta_lead_forms')

    @property
    def questions_count(self):
        return len(self.questions or {})

    def __repr__(self):
        return (
            f'<MetaLeadForm form_id={self.form_id} '
            f'questions={self.questions_count}>'
        )
