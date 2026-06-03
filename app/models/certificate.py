"""Сертифікат учасника заходу.

Видається адміністратором вручну для конкретної реєстрації
(EventRegistration). Видача = створення запису Certificate, що:
  * відкриває користувачу доступ до завантаження у особистому кабінеті;
  * прикріплює PDF до листа-сповіщення.

Ключові поля -- незмінні знімки (recipient_name, event_title, event_date,
cpd_points) на момент видачі, щоб подальші правки курсу/користувача не
змінювали вже виданий сертифікат.
"""
from sqlalchemy import func as sa_func

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow


class Certificate(TimestampMixin, db.Model):
    __tablename__ = 'certificates'

    id = db.Column(BigIntPK, primary_key=True)

    # Один сертифікат на одну реєстрацію.
    registration_id = db.Column(
        db.BigInteger,
        db.ForeignKey('event_registrations.id', ondelete='CASCADE'),
        unique=True,
        nullable=False,
        index=True,
    )
    # Денормалізований власник -- для швидкого "мої сертифікати" і щоб
    # запис лишався прив'язаним до людини незалежно від реєстрації.
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )

    # Унікальний людиночитний номер, що друкується на сертифікаті.
    number = db.Column(db.String(40), unique=True, nullable=False, index=True)

    # Незмінні знімки на момент видачі.
    recipient_name = db.Column(db.String(255), nullable=False)
    event_title = db.Column(db.String(500), nullable=False)
    event_date = db.Column(db.DateTime(timezone=True))
    cpd_points = db.Column(db.Integer)
    # Знімок імені лектора (тренера проведення) на момент видачі.
    lecturer_name = db.Column(db.String(200))
    # Знімок спеціальностей заходу (напр. "усі лікарські спеціальності").
    specialties = db.Column(db.String(500))

    issued_at = db.Column(
        db.DateTime(timezone=True), default=utcnow, nullable=False,
    )
    issued_by_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
    )

    # Шлях до згенерованого PDF відносно CERTIFICATE_FOLDER.
    pdf_path = db.Column(db.String(255), nullable=False)

    revoked = db.Column(db.Boolean, default=False, nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True))

    registration = db.relationship(
        'EventRegistration',
        back_populates='certificate',
        foreign_keys=[registration_id],
    )
    user = db.relationship('User', foreign_keys=[user_id])
    issued_by = db.relationship('User', foreign_keys=[issued_by_id])

    @staticmethod
    def format_number(year, provider, event, participant):
        """Зібрати номер БПР: РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ.

        * РРРР -- рік проведення заходу;
        * ПППП -- реєстраційний номер провайдера (4 цифри);
        * ЗЗЗЗЗЗЗ -- реєстраційний номер заходу БПР (7 цифр);
        * УУУУУУ -- порядковий номер учасника (6 цифр).
        """
        return (
            f'{year}-{str(provider).strip().zfill(4)}'
            f'-{str(event).strip().zfill(7)}-{int(participant):06d}'
        )

    @classmethod
    def generate_number(cls, year, provider, event):
        """Номер для видачі з реєстрації: учасник = ГЛОБАЛЬНИЙ лічильник усіх
        виданих сертифікатів. Гонки знімаються unique-constraint + retry.
        """
        total = db.session.query(sa_func.count(cls.id)).scalar() or 0
        return cls.format_number(year, provider, event, total + 1)

    @property
    def is_valid(self):
        return not self.revoked

    def __repr__(self):
        return f'<Certificate {self.number} reg={self.registration_id}>'
