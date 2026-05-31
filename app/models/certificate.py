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

    NUMBER_PREFIX = 'IPRM'

    @classmethod
    def generate_number(cls, issued_at):
        """Сформувати наступний номер виду IPRM-2026-000123.

        Послідовність у межах року. Можливі гонки під паралельними
        видачами знімаються unique-constraint-ом + retry у сервісі.
        """
        year = issued_at.year
        like = f'{cls.NUMBER_PREFIX}-{year}-%'
        count = db.session.query(sa_func.count(cls.id)).filter(
            cls.number.like(like)
        ).scalar() or 0
        return f'{cls.NUMBER_PREFIX}-{year}-{count + 1:06d}'

    @property
    def is_valid(self):
        return not self.revoked

    def __repr__(self):
        return f'<Certificate {self.number} reg={self.registration_id}>'
