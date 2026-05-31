"""Правило одержувачів admin-нотифікації для конкретного типу події.

Один рядок на event_type (registration, payment, course_request,
status_change). Прапори вмикають динамічних адресатів (адміни,
менеджери, тренер заходу), extra_emails -- довільний список. Для
status_change є додаткове поле trigger_statuses -- список конкретних
переходів, на які реагуємо ('cancelled', 'completed' тощо).

Сервіс app.services.notification_recipients.resolve() поєднує всі
джерела й повертає dedup-нутий список email-ів.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin


# Підтримувані типи подій. Збігаються з EmailLog.TRIGGERS, але не всі
# тригери мають admin-нотифікацію (email_confirm/certificate/reminder --
# user-facing only).
EVENT_TYPES = [
    ('registration', 'Реєстрація на захід'),
    ('payment', 'Оплата'),
    ('course_request', 'Запит на курс'),
    ('status_change', 'Скасування реєстрації'),
]

# Дефолтні статуси-тригери для status_change. Інші переходи (pending ->
# confirmed, confirmed -> completed) -- routine, не шумимо адмінам.
DEFAULT_TRIGGER_STATUSES = ['cancelled']


class NotificationRule(TimestampMixin, db.Model):
    __tablename__ = 'notification_rules'

    # event_type сам є PK -- одне правило на тип події.
    event_type = db.Column(db.String(40), primary_key=True)

    # Прапори динамічних адресатів. enabled -- глобальний вимикач події.
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    notify_admins = db.Column(db.Boolean, default=True, nullable=False)
    notify_managers = db.Column(db.Boolean, default=False, nullable=False)
    notify_event_trainer = db.Column(db.Boolean, default=False, nullable=False)

    # Додатковий статичний список email-ів для цього типу події.
    extra_emails = db.Column(db.JSON, default=list, nullable=False)

    # Для event_type='status_change': список status-переходів, на які
    # реагуємо. None / [] => DEFAULT_TRIGGER_STATUSES. Для решти --
    # ігнорується.
    trigger_statuses = db.Column(db.JSON, default=None, nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "event_type IN ('registration', 'payment', 'course_request', 'status_change')",
            name='ck_notification_rules_event_type',
        ),
    )

    def __init__(self, **kwargs):
        """Накладаємо Python-defaults одразу у __init__, щоб атрибути були
        доступні ще ДО flush. SQLAlchemy без цього лишає None у щойно
        створеному об'єкті, що ламає рендер форми у race-кейсі (route
        створює дефолтні рядки і одразу їх читає)."""
        kwargs.setdefault('enabled', True)
        kwargs.setdefault('notify_admins', True)
        kwargs.setdefault('notify_managers', False)
        kwargs.setdefault('notify_event_trainer', False)
        kwargs.setdefault('extra_emails', [])
        kwargs.setdefault('trigger_statuses', None)
        super().__init__(**kwargs)

    @property
    def event_type_label(self):
        return dict(EVENT_TYPES).get(self.event_type, self.event_type)

    @property
    def effective_trigger_statuses(self):
        """Список status-переходів для status_change. None/[] => default."""
        return list(self.trigger_statuses or DEFAULT_TRIGGER_STATUSES)

    @classmethod
    def get_or_stub(cls, event_type):
        """Повертає правило за event_type. Якщо відсутнє -- транзитний
        STUB-об'єкт з дефолтами (НЕ доданий до сесії). Stub читачі
        отримують стабільну поведінку без NULL-перевірок; модифікувати
        його безглуздо (зміни не персистяться). Caller, що хоче створити
        рядок, має використати NotificationRule(event_type=...) +
        db.session.add()."""
        rule = cls.query.get(event_type)
        return rule if rule is not None else cls(event_type=event_type)

    def __repr__(self):
        return f'<NotificationRule {self.event_type} enabled={self.enabled}>'
