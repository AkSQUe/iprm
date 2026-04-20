from sqlalchemy import func, select
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class User(TimestampMixin, UserMixin, db.Model):
    __tablename__ = 'users'

    __table_args__ = (
        db.Index('ix_users_created_at', 'created_at'),
    )

    id = db.Column(BigIntPK, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    email_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    last_login_at = db.Column(db.DateTime(timezone=True))

    registrations = db.relationship('EventRegistration', back_populates='user', lazy='dynamic')
    created_courses = db.relationship(
        'Course',
        foreign_keys='Course.created_by',
        back_populates='creator',
    )

    def __init__(self, email, password=None, **kwargs):
        super().__init__(**kwargs)
        self.email = email.lower().strip()
        if password:
            self.set_password(password)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def registration_count(self):
        cached = getattr(self, '_cached_reg_count', None)
        if cached is not None:
            return cached
        return self.registrations.count()

    @classmethod
    def with_registration_count(cls):
        from app.models.registration import EventRegistration
        return (
            select(func.count(EventRegistration.id))
            .where(
                EventRegistration.user_id == cls.id,
                EventRegistration.status.notin_(['cancelled']),
            )
            .correlate(cls)
            .scalar_subquery()
            .label('_registration_count')
        )

    def __repr__(self):
        return f'<User {self.email}>'
