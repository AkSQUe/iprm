from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class Clinic(TimestampMixin, db.Model):
    __tablename__ = 'clinics'

    id = db.Column(BigIntPK, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    short_description = db.Column(db.String(500))
    description = db.Column(db.Text)
    photo = db.Column(db.String(500))
    sort_order = db.Column(db.Integer, default=0, index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)

    def __repr__(self):
        return f'<Clinic {self.name}>'
