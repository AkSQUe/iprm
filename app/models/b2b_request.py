"""B2BRequest — заявка на корпоративне навчання (блок "Для команд і клінік").

Лід-форма з каталогу курсів: контактна особа + розмір команди. Адмін
обробляє заявки на /admin/b2b-requests (зв'язується вручну).
"""
import re

from sqlalchemy.orm import validates

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK

_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class B2BRequest(TimestampMixin, db.Model):
    __tablename__ = 'b2b_requests'

    id = db.Column(BigIntPK, primary_key=True)

    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    # Розмір команди -- один з TEAM_SIZES (селект у формі).
    team_size = db.Column(db.String(10), nullable=False)

    status = db.Column(db.String(20), default='new', nullable=False, index=True)
    admin_notes = db.Column(db.Text)

    __table_args__ = (
        db.Index('ix_b2b_requests_created_at', 'created_at'),
        db.CheckConstraint(
            "status IN ('new', 'contacted', 'closed', 'dismissed')",
            name='ck_b2b_requests_status',
        ),
        db.CheckConstraint(
            "team_size IN ('3-5', '6-10', '10+')",
            name='ck_b2b_requests_team_size',
        ),
    )

    STATUSES = [
        ('new', 'Новий'),
        ('contacted', 'На зв\'язку'),
        ('closed', 'Закрито (угода)'),
        ('dismissed', 'Відхилено'),
    ]

    TEAM_SIZES = [
        ('3-5', '3–5'),
        ('6-10', '6–10'),
        ('10+', 'Понад 10'),
    ]

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def team_size_label(self):
        return dict(self.TEAM_SIZES).get(self.team_size, self.team_size)

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    @validates('email')
    def _validate_email(self, _key, value):
        normalized = (value or '').strip().lower()
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
            raise ValueError(f'невідомий status: {value!r}')
        return value

    @validates('team_size')
    def _validate_team_size(self, _key, value):
        valid = {code for code, _ in self.TEAM_SIZES}
        if value not in valid:
            raise ValueError(f'невідомий team_size: {value!r}')
        return value

    def __repr__(self):
        return f'<B2BRequest {self.email} team={self.team_size}>'
