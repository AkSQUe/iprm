"""CourseRequest — запит користувача на проведення курсу.
Використовується коли немає запланованого CourseInstance або клієнт хоче
ще одне проведення. Адмін бачить кількість запитів і вирішує створити instance.
"""
import re

from sqlalchemy.orm import validates

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK

# Проста перевірка структури: local@domain.tld. Повна перевірка --
# у формі через email_validator; ця -- defense-in-depth при прямих
# вставках (CLI, data migration, тощо).
_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class CourseRequest(TimestampMixin, db.Model):
    __tablename__ = 'course_requests'

    id = db.Column(BigIntPK, primary_key=True)
    course_id = db.Column(
        db.BigInteger,
        db.ForeignKey('courses.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(20))
    message = db.Column(db.Text)

    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    admin_notes = db.Column(db.Text)

    resolved_by_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    resolved_at = db.Column(db.DateTime(timezone=True))

    __table_args__ = (
        db.Index('ix_course_requests_course_status', 'course_id', 'status'),
        db.Index('ix_course_requests_created_at', 'created_at'),
        db.CheckConstraint(
            "status IN ('pending', 'responded', 'scheduled', 'dismissed')",
            name='ck_course_requests_status',
        ),
    )

    course = db.relationship('Course', back_populates='requests')
    user = db.relationship('User', foreign_keys=[user_id])
    resolver = db.relationship('User', foreign_keys=[resolved_by_id])

    STATUSES = [
        ('pending', 'Новий'),
        ('responded', 'Оброблено'),
        ('scheduled', 'Заплановано'),
        ('dismissed', 'Відхилено'),
    ]

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @validates('email')
    def _validate_email(self, _key, value):
        if value is None:
            raise ValueError('email є обов\'язковим')
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError('email є обов\'язковим')
        if len(normalized) > 255:
            raise ValueError('email задовгий (макс. 255)')
        if not _EMAIL_RE.match(normalized):
            raise ValueError(f'невалідний email: {value!r}')
        return normalized

    @validates('status')
    def _validate_status(self, _key, value):
        valid = {code for code, _ in self.STATUSES}
        if value not in valid:
            raise ValueError(
                f'невідомий status: {value!r}; очікується одне з {sorted(valid)}'
            )
        return value

    @validates('phone')
    def _validate_phone(self, _key, value):
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if len(stripped) > 20:
            raise ValueError('phone задовгий (макс. 20)')
        return stripped

    def __repr__(self):
        return f'<CourseRequest course={self.course_id} email={self.email}>'


class CourseRequestAudit(TimestampMixin, db.Model):
    """Журнал змін статусу CourseRequest.

    Один рядок на кожну зміну (pending -> responded, responded -> scheduled, ...).
    Використовується для детективної діагностики: хто і коли обробив запит.
    """
    __tablename__ = 'course_request_audits'

    id = db.Column(BigIntPK, primary_key=True)
    request_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_requests.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20), nullable=False)
    changed_by_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    notes = db.Column(db.Text)

    request = db.relationship(
        'CourseRequest',
        backref=db.backref(
            'audits',
            order_by='CourseRequestAudit.created_at.desc()',
            cascade='all, delete-orphan',
        ),
    )
    changed_by = db.relationship('User', foreign_keys=[changed_by_id])

    def __repr__(self):
        return (
            f'<CourseRequestAudit request={self.request_id} '
            f'{self.from_status}->{self.to_status}>'
        )
