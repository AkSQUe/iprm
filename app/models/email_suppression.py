"""Suppression-список адрес, на які більше не шлемо листи.

Дві причини (reason):
- 'bounce'      -- hard-bounce / адреса не існує: НЕ шлемо нічого (навіть
                   транзакційне -- воно все одно не дійде, лише псує репутацію).
- 'unsubscribe' -- користувач відписався: НЕ шлемо необов'язкові листи
                   (нагадування тощо), але транзакційні (пароль, підтвердження)
                   лишаються.

Перевіряє EmailService.send_email перед кожною відправкою.
"""
from datetime import datetime, timezone

from app.extensions import db
from app.models.mixins import BigIntPK


class EmailSuppression(db.Model):
    __tablename__ = 'email_suppressions'

    REASON_BOUNCE = 'bounce'
    REASON_UNSUBSCRIBE = 'unsubscribe'
    REASON_COMPLAINT = 'complaint'

    id = db.Column(BigIntPK, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    reason = db.Column(db.String(50), nullable=False, default=REASON_BOUNCE)
    # Звідки додано: 'imap_bounce', 'manual', 'unsubscribe_link', ...
    source = db.Column(db.String(50))
    detail = db.Column(db.String(500))
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    @classmethod
    def normalize(cls, email):
        return (email or '').strip().lower()

    @classmethod
    def add(cls, email, reason=REASON_BOUNCE, source=None, detail=None):
        """Idempotent-додавання у suppression. Повертає (row, created)."""
        norm = cls.normalize(email)
        if not norm:
            return None, False
        existing = cls.query.filter_by(email=norm).first()
        if existing is not None:
            return existing, False
        row = cls(email=norm, reason=reason, source=source, detail=(detail or '')[:500])
        db.session.add(row)
        return row, True

    @classmethod
    def get(cls, email):
        norm = cls.normalize(email)
        if not norm:
            return None
        return cls.query.filter_by(email=norm).first()

    def __repr__(self):
        return f'<EmailSuppression {self.email} ({self.reason})>'
