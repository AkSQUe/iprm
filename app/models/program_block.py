from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class ProgramBlock(TimestampMixin, db.Model):
    __tablename__ = 'program_blocks'

    id = db.Column(BigIntPK, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    heading = db.Column(db.String(200), nullable=False)
    items = db.Column(db.JSON, nullable=False, default=list)
    sort_order = db.Column(db.Integer, default=0)

    event = db.relationship('Event', back_populates='program_blocks')

    def __repr__(self):
        return f'<ProgramBlock {self.heading}>'
