"""Local record of consumable-material reservations placed with MM Medic.

The source of truth for stock lives on MM Medic; these tables are IPRM's own
history/audit of what was reserved and later actually used for a given
CourseInstance (захід). Product identity is SNAPSHOTTED (sku/name/image) so the
history stays stable even if the MM Medic catalog changes later.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class MaterialReservationStatus:
    DRAFT = 'draft'          # built locally, not yet sent
    RESERVED = 'reserved'    # accepted by MM Medic (holds active)
    CONSUMED = 'consumed'    # actuals submitted, stock written off
    CANCELLED = 'cancelled'  # released before the event

    ALL = (DRAFT, RESERVED, CONSUMED, CANCELLED)
    LABELS = {
        DRAFT: 'Чернетка',
        RESERVED: 'Зарезервовано',
        CONSUMED: 'Списано',
        CANCELLED: 'Скасовано',
    }


class MaterialReservation(TimestampMixin, db.Model):
    """Header: one reservation per CourseInstance sent to MM Medic."""
    __tablename__ = 'material_reservations'

    id = db.Column(BigIntPK, primary_key=True)
    instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    # Stable external reference sent to MM Medic, e.g. "iprm-instance-123".
    external_ref = db.Column(db.String(64), nullable=False, unique=True, index=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=MaterialReservationStatus.DRAFT,
        index=True,
    )
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    consumed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Raw snapshot of the last MM Medic response (for troubleshooting).
    last_response = db.Column(db.JSON, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    instance = db.relationship('CourseInstance', backref=db.backref(
        'material_reservations', lazy='selectin', cascade='all, delete-orphan',
    ))
    items = db.relationship(
        'MaterialReservationItem',
        backref='reservation',
        lazy='selectin',
        cascade='all, delete-orphan',
        order_by='MaterialReservationItem.name',
    )

    @property
    def status_label(self):
        return MaterialReservationStatus.LABELS.get(self.status, self.status)


class MaterialReservationItem(TimestampMixin, db.Model):
    """Line: one product, with a snapshot of its MM Medic identity."""
    __tablename__ = 'material_reservation_items'

    id = db.Column(BigIntPK, primary_key=True)
    reservation_id = db.Column(
        db.BigInteger,
        db.ForeignKey('material_reservations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    # Snapshot of MM Medic product identity
    sku = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(255), nullable=True)
    image_url = db.Column(db.String(500), nullable=True)

    quantity_reserved = db.Column(db.Integer, nullable=False, default=0)
    quantity_actual = db.Column(db.Integer, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('reservation_id', 'sku', name='uq_material_item_sku'),
    )
