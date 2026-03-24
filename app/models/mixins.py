from datetime import datetime, timezone

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


# BigInteger для PostgreSQL, Integer для SQLite (autoincrement)
BigIntPK = db.BigInteger().with_variant(db.Integer, 'sqlite')


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)
