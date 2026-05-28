"""MedicalProfile -- медичні дані лікаря для нарахування балів БПР МОЗ #725.

Винесено з User у власну таблицю, бо ці поля потрібні ЛИШЕ при реєстрації
на захід (event registration). Користувач, що зайшов через Google/Apple,
не повинен заповнювати медпрофіль на signup -- лише при першій реєстрації
на курс.

One-to-one з User через спільний PK (user_id = users.id). Це дешевше за
звичайний FK і атомарно ловить "один профіль на юзера" на рівні схеми.

`completed_at` -- timestamp того, коли профіль став повним (тобто має всі
обов'язкові БПР-поля). `is_complete` -- runtime-перевірка; може давати
True ще до того як `completed_at` встановлено (наприклад під час
збереження). Логіка "чи можна реєструватись на захід" -- через
`is_complete`, а не `completed_at IS NOT NULL`.

`source` -- звідки взялись дані ('self' -- сам заповнив, 'legacy' --
backfill з User в момент розділення таблиць, 'partner' -- prefill від
mm-medic, 'imported' -- ручний імпорт з xlsx).
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class MedicalProfile(TimestampMixin, db.Model):
    __tablename__ = 'medical_profiles'

    SOURCE_SELF = 'self'
    SOURCE_LEGACY = 'legacy'
    SOURCE_PARTNER = 'partner'
    SOURCE_IMPORTED = 'imported'

    PARTICIPANT_TYPES = [
        ('doctor', 'Лікар'),
        ('specialist', 'Молодший спеціаліст з медичною освітою'),
        ('intern', 'Інтерн'),
        ('student', 'Студент'),
    ]

    user_id = db.Column(
        BigIntPK,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        primary_key=True,
    )
    participant_type = db.Column(db.String(20))
    middle_name = db.Column(db.String(100))
    birth_date = db.Column(db.Date)
    education = db.Column(db.String(500))
    workplace = db.Column(db.String(300))
    position = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    # Список codes з SPECIALIZATIONS (multi-select).
    specializations = db.Column(db.JSON, default=list)
    completed_at = db.Column(db.DateTime(timezone=True))
    source = db.Column(db.String(20), default=SOURCE_SELF, nullable=False)

    user = db.relationship('User', back_populates='medical_profile')

    __table_args__ = (
        db.CheckConstraint(
            "participant_type IN ('doctor', 'specialist', 'intern', 'student') "
            "OR participant_type IS NULL",
            name='ck_medical_profiles_participant_type',
        ),
    )

    @property
    def is_complete(self):
        """Профіль повний для реєстрації на БПР-захід: тип учасника,
        дата народження, освіта і ≥1 спеціалізація."""
        return bool(
            self.participant_type
            and self.birth_date
            and self.education
            and self.specializations
            and len(self.specializations) > 0
        )

    @property
    def participant_type_label(self):
        return dict(self.PARTICIPANT_TYPES).get(
            self.participant_type, self.participant_type or '',
        )

    @property
    def specialization_labels(self):
        from app.models.specializations import labels_for_codes
        return labels_for_codes(self.specializations or [])

    def __repr__(self):
        return (
            f'<MedicalProfile user_id={self.user_id} '
            f'complete={self.is_complete}>'
        )
