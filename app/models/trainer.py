from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class Trainer(TimestampMixin, db.Model):
    __tablename__ = 'trainers'

    id = db.Column(BigIntPK, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    role = db.Column(db.String(300))
    bio = db.Column(db.Text)
    photo = db.Column(db.String(500))
    experience_years = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True, index=True)

    events = db.relationship('Event', back_populates='trainer', lazy='dynamic')

    def __repr__(self):
        return f'<Trainer {self.full_name}>'
