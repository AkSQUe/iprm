"""CourseInstance — конкретне проведення курсу (коли, де, формат).
Належить Course. Реєстрації прив'язуються до instance (не до Course).
"""
import logging

from sqlalchemy import func, select

from app.extensions import db
from app.models.mixins import TimestampMixin, TranslatableMixin, BigIntPK
from app.models.trainer_links import course_instance_trainers

logger = logging.getLogger(__name__)


class CourseInstance(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'course_instances'
    __translatable__ = ('topic',)

    id = db.Column(BigIntPK, primary_key=True)
    course_id = db.Column(
        db.BigInteger,
        db.ForeignKey('courses.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )

    # Тема конкретного проведення. Порожньо -- беремо назву курсу
    # (див. effective_title). Потрібна, коли дати одного курсу мають різні
    # тематичні акценти, і саме тема, а не назва курсу, іде в документи БПР.
    topic = db.Column(db.String(255))

    start_date = db.Column(db.DateTime(timezone=True), index=True)
    end_date = db.Column(db.DateTime(timezone=True))

    event_format = db.Column(db.String(20))

    # Перевизначення виду заходу для конкретного проведення. Порожньо --
    # береться тип курсу (див. effective_event_type). Потрібне, коли той
    # самий курс раз проводять тренінгом, а раз -- фаховою школою.
    event_type = db.Column(db.String(30), index=True)

    price = db.Column(db.Numeric(10, 2))
    # Бали БПР окремо за форматом участі -- те саме розмежування, що й у Course.
    cpd_points_online = db.Column(db.Numeric(5, 2))
    cpd_points_offline = db.Column(db.Numeric(5, 2))
    max_participants = db.Column(db.Integer)

    # `location` -- адреса для людини ("м. Харків, вул. Сковороди, 80, ДУ ..."),
    # `city_id` -- структуроване місто для фільтрів і партнерських вітрин.
    # Одне не заміняє інше: розбирати адресу на місто означало б вгадувати
    # (див. app/services/city_glossary.py), а звести місто до адреси -- втратити
    # фасет. Обидва необов'язкові: місце проведення часто відоме пізніше за
    # дату, і розклад показує «Місце уточнюється» замість того, щоб ховати захід.
    location = db.Column(db.String(255))
    city_id = db.Column(
        db.BigInteger,
        db.ForeignKey('cities.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    online_link = db.Column(db.String(500))

    # Перевизначення спеціальностей проведення. NULL/порожньо -- беремо курс.
    bpr_specialty_codes = db.Column(db.JSON)

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
            'cpd_points_online >= 0 OR cpd_points_online IS NULL',
            name='ck_course_instances_cpd_points_online_non_negative',
        ),
        db.CheckConstraint(
            'cpd_points_offline >= 0 OR cpd_points_offline IS NULL',
            name='ck_course_instances_cpd_points_offline_non_negative',
        ),
        db.CheckConstraint(
            'max_participants >= 1 OR max_participants IS NULL',
            name='ck_course_instances_max_participants_positive',
        ),
    )

    course = db.relationship('Course', back_populates='instances')
    trainers = db.relationship(
        'Trainer', secondary=course_instance_trainers,
        order_by=course_instance_trainers.c.position,
        viewonly=True, lazy='select',
    )
    city = db.relationship('City', foreign_keys=[city_id])
    tariffs = db.relationship(
        'InstanceTariff',
        back_populates='instance',
        order_by='InstanceTariff.sort_order',
        cascade='all, delete-orphan',
    )
    registrations = db.relationship(
        'EventRegistration',
        foreign_keys='EventRegistration.instance_id',
        back_populates='instance',
        lazy='dynamic',
    )
    # Зворотний бік MetaLeadForm.course_instance -- потрібен не для зручного
    # обходу, а щоб ORM узагалі знала, чиї рядки нулювати при видаленні
    # заходу (FK там ondelete='SET NULL', без cascade).
    meta_lead_forms = db.relationship('MetaLeadForm', back_populates='course_instance')

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

    # Модифікатор `.badge--*` дизайн-системи на кожен стан. Відображення тут
    # тотожне -- правило під кожен із п'яти станів у системі вже є. Властивість
    # усе одно потрібна: вона робить це збігом за домовленістю, а не
    # випадковістю, і шостий стан не з'явиться на екрані плашкою без тла.
    STATUS_BADGES = {
        'draft': 'draft',
        'published': 'published',
        'active': 'active',
        'completed': 'completed',
        'cancelled': 'cancelled',
    }

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def status_badge(self):
        """Модифікатор `.badge--*` під поточний стан (див. STATUS_BADGES)."""
        return self.STATUS_BADGES.get(self.status, 'draft')

    def can_transition_to(self, new_status):
        """Перевірити чи дозволено перейти з поточного у new_status.

        Caller повинен окремо обробити випадок new_status == self.status
        (no-op, не вимагає дозволеного переходу).
        """
        return new_status in self.STATUS_TRANSITIONS.get(self.status, set())

    @property
    def format_label(self):
        return dict(self.FORMATS).get(self.event_format, self.event_format)

    @property
    def effective_event_type(self):
        """Код виду заходу: власний, а якщо порожній -- курсовий."""
        if self.event_type:
            return self.event_type
        if self.course is None:
            self._warn_orphan('event_type')
            return None
        return self.course.event_type

    def effective_title_for(self, lang=None):
        """Назва проведення мовою `lang`: власна тема, інакше назва курсу.

        None (а не «Захід») для проведення без курсу: підпис для порожнечі
        різний у кожного споживача -- прочерк у таблиці, `_('захід')` у листі.
        """
        topic = (self.t('topic', lang=lang) or '').strip()
        if topic:
            return topic
        if self.course is None:
            self._warn_orphan('title')
            return None
        return self.course.t('title', lang=lang)

    @property
    def effective_title(self):
        """Назва проведення поточною локаллю (див. effective_title_for)."""
        return self.effective_title_for()

    @property
    def event_type_label(self):
        from app.services import event_types
        return event_types.label(self.effective_event_type)

    def _warn_orphan(self, context):
        """Логувати якщо instance без course (дата-інтегріті issue)."""
        logger.warning(
            'CourseInstance id=%s course_id=%s has no course loaded (effective_%s fallback)',
            self.id, self.course_id, context,
        )

    @property
    def active_tariffs(self):
        """Активні тарифи проведення у порядку sort_order."""
        return [t for t in self.tariffs if t.is_active]

    @property
    def copyable_course_tariffs(self):
        """Активні шаблонні тарифи курсу, що пасують формату цього проведення.

        Саме стільки скопіює кнопка "Взяти з курсу": онлайн-шаблони не
        переносяться в офлайн-проведення (і навпаки), NULL-формат пасує всім.
        default_tariffs вже впорядковані за sort_order."""
        if self.course is None:
            return []
        return [t for t in self.course.default_tariffs
                if t.is_active and t.matches_format(self.event_format)]

    @property
    def effective_price(self):
        """Фактична ціна: мінімальний активний тариф ("від N"), інакше
        перевизначення проведення, інакше базова ціна курсу."""
        tariffs = self.active_tariffs
        if tariffs:
            return min(t.price for t in tariffs)
        if self.price is not None:
            return self.price
        if self.course is None:
            self._warn_orphan('price')
            return 0
        return self.course.base_price

    @property
    def price_is_from(self):
        """True, коли effective_price -- це "від N" (кілька різних тарифів)."""
        prices = {t.price for t in self.active_tariffs}
        return len(prices) > 1

    @property
    def effective_specialty_codes(self):
        """Коди спеціальностей проведення або, якщо не задані, коди курсу."""
        if self.bpr_specialty_codes:
            return list(self.bpr_specialty_codes)
        course = self.course
        return list(course.bpr_specialty_codes or []) if course else []

    def effective_cpd_for(self, fmt):
        """Бали БПР для формату участі `fmt` ('online' / 'offline').

        Відкат -- лише на однойменне поле курсу. Підставляти сюди значення
        іншого формату не можна: порожній онлайн на гібриді означає «ще не
        вирішили», а не «стільки ж, скільки очно».
        """
        column = 'cpd_points_online' if fmt == 'online' else 'cpd_points_offline'
        own = getattr(self, column)
        if own is not None:
            return own
        if self.course is None:
            self._warn_orphan(column)
            return None
        return getattr(self.course, column)

    @property
    def cpd_formats(self):
        """Формати участі, які цей захід реально пропонує."""
        if self.event_format == 'hybrid':
            return ('online', 'offline')
        return (self.event_format or 'offline',)

    @property
    def cpd_pairs(self):
        """[(формат, бали)] -- лише наявні формати й лише заповнені бали."""
        pairs = []
        for fmt in self.cpd_formats:
            points = self.effective_cpd_for(fmt)
            if points is not None:
                pairs.append((fmt, points))
        return pairs

    @property
    def cpd_range(self):
        """(мінімум, максимум) балів заходу -- для вузьких місць верстки."""
        values = [points for _, points in self.cpd_pairs]
        if not values:
            return (None, None)
        return (min(values), max(values))

    @property
    def effective_max_participants(self):
        if self.max_participants is not None:
            return self.max_participants
        if self.course is None:
            self._warn_orphan('max_participants')
            return None
        return self.course.max_participants

    @property
    def effective_trainers(self):
        """Тренери проведення, інакше -- курсу. Повне перекриття, не злиття."""
        if self.trainers:
            return list(self.trainers)
        if self.course is None:
            self._warn_orphan('trainers')
            return []
        return list(self.course.trainers)

    @property
    def effective_trainer(self):
        """Головний тренер заходу -- перший зі списку."""
        trainers = self.effective_trainers
        return trainers[0] if trainers else None

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
    def occupied_seats(self):
        """Скільки місць реально зайнято -- рахуються лише оплачені.

        Кеш `_cached_occupied` виставляє caller (batch-COUNT у лістингах),
        інакше -- окремий запит. Правило й причина -- у services.seating.
        """
        cached = getattr(self, '_cached_occupied', None)
        if cached is not None:
            return cached
        from app.services.seating import occupied_count
        return occupied_count(self.id)

    @property
    def has_capacity(self):
        cap = self.effective_max_participants
        if cap is None:
            return True
        return self.occupied_seats < cap

    @property
    def is_overbooked(self):
        """Оплачених більше за місткість (оплата прийшла після заповнення)."""
        from app.services.seating import is_overbooked
        return is_overbooked(self.effective_max_participants, self.occupied_seats)

    @property
    def is_registration_open(self):
        return (
            self.status in ('published', 'active')
            and self.has_capacity
        )

    def __repr__(self):
        return f'<CourseInstance course={self.course_id} start={self.start_date}>'
