from datetime import datetime, timezone
from app.extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class Trainer(db.Model):
    __tablename__ = 'trainers'

    id = db.Column(db.BigInteger, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    role = db.Column(db.String(300))
    bio = db.Column(db.Text)
    photo = db.Column(db.String(500))
    experience_years = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    events = db.relationship('Event', back_populates='trainer', lazy='dynamic')

    def __repr__(self):
        return f'<Trainer {self.full_name}>'
