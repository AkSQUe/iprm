"""CourseRequest — запит користувача на проведення курсу.
Використовується коли немає запланованого CourseInstance або клієнт хоче
ще одне проведення. Адмін бачить кількість запитів і вирішує створити instance.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


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

    def __repr__(self):
        return f'<CourseRequest course={self.course_id} email={self.email}>'
