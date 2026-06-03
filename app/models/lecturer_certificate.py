"""Сертифікат ЛЕКТОРА заходу.

Виняток із загального правила (учасницькі сертифікати -- Certificate, по одному
на реєстрацію). Лектор отримує власний сертифікат після заходу: інший текст,
інша кількість балів БПР, лише підпис Директора.

Поля -- незмінні знімки на момент видачі (як у Certificate). Один запис на
проведення (instance_id unique): повторна видача повертає той самий номер.
Номер учасника (остання група) -- у діапазоні 1xxxxx (окремий лічильник, щоб
не перетинатися з учасницькими 0xxxxx).
"""
from sqlalchemy import func as sa_func

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow
from app.models.certificate import Certificate

# Зсув діапазону лекторських номерів: 100001, 100002, ... (1xxxxx).
LECTURER_NUMBER_OFFSET = 100000


class LecturerCertificate(TimestampMixin, db.Model):
    __tablename__ = 'lecturer_certificates'

    id = db.Column(BigIntPK, primary_key=True)

    # Одне проведення -> один лекторський сертифікат (повторна видача = reuse).
    instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='CASCADE'),
        unique=True,
        nullable=False,
        index=True,
    )
    trainer_id = db.Column(
        db.BigInteger,
        db.ForeignKey('trainers.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    number = db.Column(db.String(40), unique=True, nullable=False, index=True)

    # Незмінні знімки на момент видачі.
    recipient_name = db.Column(db.String(255), nullable=False)  # давальний відмінок
    event_title = db.Column(db.String(500), nullable=False)
    event_date = db.Column(db.DateTime(timezone=True))
    cpd_points = db.Column(db.Integer)
    specialties = db.Column(db.String(500))
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

    @classmethod
    def generate_number(cls, year, provider, event):
        """Номер лекторського серта: учасник = LECTURER_NUMBER_OFFSET + лічильник
        усіх лекторських сертів (1xxxxx). Гонки знімаються unique + retry.
        """
        total = db.session.query(sa_func.count(cls.id)).scalar() or 0
        seq = LECTURER_NUMBER_OFFSET + total + 1
        return Certificate.format_number(year, provider, event, seq)

    def __repr__(self):
        return f'<LecturerCertificate {self.number} instance={self.instance_id}>'
