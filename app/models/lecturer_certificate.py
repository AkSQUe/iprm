"""Сертифікат ЛЕКТОРА заходу.

Виняток із загального правила (учасницькі сертифікати -- Certificate, по одному
на реєстрацію). Лектор отримує власний сертифікат після заходу: інший текст,
інша кількість балів БПР, лише підпис Директора.

Поля -- незмінні знімки на момент видачі (як у Certificate). Захід може мати
кількох тренерів (`CourseInstance.effective_trainers`), і кожен читає лекцію
особисто, тож сертифікат належить парі "проведення + тренер", а не самому
проведенню: три лектори одного заходу отримують три окремі записи. Повторна
видача для того самого тренера повертає той самий номер (unique-пара нижче).
Номер учасника (остання група) -- у діапазоні 1xxxxx (окремий лічильник, щоб
не перетинатися з учасницькими 0xxxxx).
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow

# Зсув діапазону лекторських номерів: 100001, 100002, ... (1xxxxx).
LECTURER_NUMBER_OFFSET = 100000


class LecturerCertificate(TimestampMixin, db.Model):
    __tablename__ = 'lecturer_certificates'

    id = db.Column(BigIntPK, primary_key=True)

    # Пара (instance_id, trainer_id) -- unique нижче в __table_args__, а не тут:
    # проведення саме по собі більше не унікальне (кілька тренерів = кілька
    # записів), унікальна лише пара.
    instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    # nullable + SET NULL, а не CASCADE: сертифікат -- незмінний знімок (як і
    # recipient_name нижче), тож видалення тренера з довідника не повинно
    # стирати вже видані йому сертифікати.
    trainer_id = db.Column(
        db.BigInteger,
        db.ForeignKey('trainers.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    number = db.Column(db.String(40), unique=True, nullable=False, index=True)

    __table_args__ = (
        # Один запис -- це пара «проведення + тренер». Після видалення
        # тренера пара стає (instance_id, NULL), і PostgreSQL вважає такі
        # рядки різними -- UNIQUE їх не блокує. Це правильно: два знімки
        # на двох різних видалених людей мусять співіснувати.
        db.UniqueConstraint(
            'instance_id', 'trainer_id',
            name='uq_lecturer_certificates_instance_trainer',
        ),
    )

    # Незмінні знімки на момент видачі.
    recipient_name = db.Column(db.String(255), nullable=False)  # давальний відмінок
    event_title = db.Column(db.String(500), nullable=False)
    event_date = db.Column(db.DateTime(timezone=True))
    cpd_points = db.Column(db.Numeric(5, 2))
    # Знімок спеціальностей заходу на момент видачі (назви через кому).
    # Text, а не String(500): ліміту на кількість обраних позицій немає.
    specialties = db.Column(db.Text)
    # Тип заходу у РОДОВОМУ відмінку ("тренінгу") для рядка "лектору(-ці) ...".
    event_type_label = db.Column(db.String(100))
    event_place = db.Column(db.String(255))

    issued_at = db.Column(
        db.DateTime(timezone=True), default=utcnow, nullable=False,
    )
    issued_by_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
    )

    instance = db.relationship('CourseInstance', foreign_keys=[instance_id])
    trainer = db.relationship('Trainer', foreign_keys=[trainer_id])
    issued_by = db.relationship('User', foreign_keys=[issued_by_id])

    def __repr__(self):
        return f'<LecturerCertificate {self.number} instance={self.instance_id}>'
