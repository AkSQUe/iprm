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
mm-medic, 'imported' -- ручний імпорт з xlsx, 'meta' -- контакт заведено
із заявки Meta Lead Ads). Останнє джерело відрізняється від решти тим, що
профіль створюється БЕЗ участі людини і майже порожній: у списках адмінки
такі контакти треба вміти відсікати, інакше холодні ліди змішаються з
учасниками заходів.
"""
from sqlalchemy.orm import validates

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class MedicalProfile(TimestampMixin, db.Model):
    __tablename__ = 'medical_profiles'

    SOURCE_SELF = 'self'
    SOURCE_LEGACY = 'legacy'
    SOURCE_PARTNER = 'partner'
    SOURCE_IMPORTED = 'imported'
    SOURCE_META = 'meta'

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
    # Телефон як його ввела людина -- показується в адмінці й їде в xlsx.
    phone = db.Column(db.String(20))
    # Канонічна форма (+380XXXXXXXXX) для зіставлення з зовнішніми системами:
    # партнер (MM Medic) зшиває клієнта саме за телефоном, і робити це за
    # вільним рядком неможливо. NULL означає «номера немає або він не
    # розпізнаний» -- 11 записів у проді мають явно покручені номери, і
    # вигадувати за них канонічну форму означало б зшити не тих людей.
    #
    # Індекс, а НЕ unique: у проді один номер справді ділять два акаунти
    # (клініка з єдиним контактним телефоном -- звичайна річ). Унікальність
    # зламала б їм реєстрацію заради одного випадку на 1264; неоднозначність
    # розбирає партнер, у якого для цього є черга ручного зіставлення.
    phone_e164 = db.Column(db.String(16), index=True)
    # Список codes з SPECIALIZATIONS (multi-select).
    specializations = db.Column(db.JSON, default=list)
    completed_at = db.Column(db.DateTime(timezone=True))
    source = db.Column(db.String(20), default=SOURCE_SELF, nullable=False)

    @validates('phone')
    def _sync_phone_e164(self, _key, value):
        """Тримати канонічну форму узгодженою з `phone` на рівні моделі.

        Той самий підхід, що в `City.name_normalized`: інакше поле розійдеться
        в котромусь із шляхів запису (форма реєстрації, адмінка, xlsx-імпорт,
        seed), і розбіжність помітять нескоро.
        """
        from app.utils import UA_PHONE_RE, normalize_phone

        # `normalize_phone` -- нормалізатор, а НЕ валідатор: на нерозпізнаному
        # вводі він за власним докстрінгом повертає '+<цифри>' і покладається
        # на валідатор форми. Записати таке в канонічне поле означало б
        # віддати партнеру `+3806784014070730886` як ключ зіставлення -- і
        # зшити картку з ким завгодно. Тому пропускаємо лише канонічну форму.
        normalized = normalize_phone(value) if value else None
        self.phone_e164 = normalized if normalized and UA_PHONE_RE.match(normalized) else None
        return value

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
        """Профіль повний = заповнено все, що вимагає форма анкети.

        Перелік свідомо збігається з обов'язковими полями
        `MedicalProfileFieldsMixin` (app/forms_medical.py). Раніше тут не було
        `middle_name`, `workplace` і `position`, тож профіль, створений адмінкою
        або xlsx-імпортом, вважався повним без місця роботи -- а `middle_name`
        ще й друкується у ПІБ на сертифікаті, тобто без нього документ виходив
        дефектним.

        Одне визначення на всі гейти (тестування, банери, лист-нагадування)
        навмисно: друге, «суворіше для сертифіката», неминуче розійшлося б із
        цим на першій же правці.
        """
        return bool(
            self.participant_type
            and self.birth_date
            and self.education
            and self.specializations
            and len(self.specializations) > 0
            and self.middle_name
            and self.workplace
            and self.position
        )

    @property
    def missing_fields(self):
        """Незаповнені обов'язкові поля -- підписами, як у формі.

        Потрібно, щоб гейт тестування казав «чого саме бракує», а не просто
        «заповніть анкету»: після посилення критерію людині з давнім профілем
        інакше незрозуміло, що робити.
        """
        checks = (
            ('participant_type', 'Тип учасника'),
            ('middle_name', 'По батькові'),
            ('birth_date', 'Дата народження'),
            ('education', 'Освіта'),
            ('workplace', 'Місце роботи'),
            ('position', 'Займана посада'),
        )
        missing = [label for field, label in checks if not getattr(self, field)]
        if not self.specializations:
            missing.append('Спеціалізації')
        return missing

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
