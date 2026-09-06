"""Local record of consumable-material reservations placed with MM Medic.

The source of truth for stock lives on MM Medic; these tables are IPRM's own
history/audit of what was reserved and later actually used for a given
CourseInstance (захід). Product identity is SNAPSHOTTED (sku/name/image) so the
history stays stable even if the MM Medic catalog changes later.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class MaterialReservationStatus:
    """Lifecycle of a material reservation, as mirrored from MM Medic.

    MM Medic gained an approval step (тренер подає -> менеджер погоджує ->
    комірник відвантажує), so a request now lives before any hold exists.
    SUBMITTED and REJECTED cover that new head of the lifecycle, ISSUED covers
    the moment materials physically leave the warehouse.

    RESERVED deliberately covers BOTH the legacy MM Medic ``active`` and the new
    ``approved``: both mean "погоджено, утримання активне". Introducing a
    separate APPROVED value would have silently broken the six ``== RESERVED``
    gates in admin/routes_materials.py, which is the one thing a status rename
    must never do.
    """
    DRAFT = 'draft'          # built locally, not yet sent
    SUBMITTED = 'submitted'  # sent to MM Medic, awaiting approval (no hold yet)
    RESERVED = 'reserved'    # approved by MM Medic (holds active)
    ISSUED = 'issued'        # handed over to the trainer, stock written off
    CONSUMED = 'consumed'    # actuals recorded after the event
    REJECTED = 'rejected'    # approval refused
    CANCELLED = 'cancelled'  # released before the event
    EXPIRED = 'expired'      # holds lapsed on MM Medic (event passed, no actuals)

    ALL = (DRAFT, SUBMITTED, RESERVED, ISSUED, CONSUMED,
           REJECTED, CANCELLED, EXPIRED)

    # Модифікатор .badge--* дизайн-системи на кожен стан. Власного бейджа в
    # матеріалів більше немає: `.materials-status-badge` дублював `.badge`
    # хардкодом і знав лише чотири стани з восьми -- «Відвантажено»,
    # «Відмовлено», «Протерміновано» і «На погодженні» друкувались голим
    # текстом без плашки.
    #   submitted -- бурштин: єдиний стан, що чекає чиєїсь дії;
    #   reserved  -- синій: утримання активне (той самий синій, що був);
    #   issued    -- індиго: матеріали пішли зі складу, але захід ще попереду;
    #   consumed  -- зелений: цикл закритий;
    #   rejected/expired -- червоний: заявка не відбулась, обидва потребують
    #                       рішення менеджера;
    #   draft/cancelled  -- сірий: нічого не сталось і не станеться.
    BADGES = {
        DRAFT: 'draft',
        SUBMITTED: 'warning',
        RESERVED: 'published',
        ISSUED: 'completed',
        CONSUMED: 'active',
        REJECTED: 'cancelled',
        CANCELLED: 'draft',
        EXPIRED: 'cancelled',
    }
    LABELS = {
        DRAFT: 'Чернетка',
        SUBMITTED: 'На погодженні',
        RESERVED: 'Зарезервовано',
        ISSUED: 'Відвантажено',
        CONSUMED: 'Списано',
        REJECTED: 'Відмовлено',
        CANCELLED: 'Скасовано',
        EXPIRED: 'Протерміновано',
    }


class MaterialReservationOrigin:
    """Who started the request. Drives wording only -- both origins produce the
    same document on MM Medic, keyed by the same external_ref."""
    IPRM = 'iprm'          # created here, in the IPRM admin
    TRAINER = 'trainer'    # created by a trainer in the MM Medic admin

    ALL = (IPRM, TRAINER)
    LABELS = {
        IPRM: 'Адміністратор ІПРМ',
        TRAINER: 'Тренер (MM Medic)',
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
    origin = db.Column(
        db.String(20),
        nullable=False,
        default=MaterialReservationOrigin.IPRM,
        server_default=MaterialReservationOrigin.IPRM,
    )
    # Document number assigned by MM Medic once the request exists there.
    document_number = db.Column(db.String(50), nullable=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    consumed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # MM Medic's own updated_at from the last applied status push. The sender
    # posts off-thread, so two pushes CAN arrive out of order; without this a
    # stale one would happily overwrite a newer status.
    remote_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Set once an "submit actuals" reminder was emailed to admins (idempotency).
    actuals_reminder_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Raw snapshot of the last MM Medic response (for troubleshooting).
    last_response = db.Column(db.JSON, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Trainer confirmation: the trainer never logs in, they open a signed
    # `/materials/<token>` link and either confirm the prepared set or leave a
    # comment (or both -- see app/main/routes.py:trainer_materials_confirm).
    # NULL means "not confirmed yet"; re-confirming updates the comment
    # in place rather than erroring, so a clarification added later is not
    # treated as a duplicate submission.
    trainer_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    trainer_comment = db.Column(db.Text, nullable=True)
    # Who filed the request in the IPRM admin; kept alongside RBAC roles as
    # the accountability trail (see plan 5.3).
    created_by_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )

    instance = db.relationship('CourseInstance', backref=db.backref(
        'material_reservations', lazy='selectin', cascade='all, delete-orphan',
    ))
    created_by = db.relationship('User', foreign_keys=[created_by_id])
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

    @property
    def status_badge(self):
        """Модифікатор `.badge--*` під поточний стан (див. STATUS.BADGES)."""
        return MaterialReservationStatus.BADGES.get(self.status, 'draft')

    @property
    def is_mm_document(self):
        """Чи цим резервуванням керує ДОКУМЕНТ на боці MM Medic.

        Два канали пишуть в одне й те саме дзеркало. Легасі-канал
        (``create_reservation``) створює на MM Medic лише утримання складу:
        списати його можна звідси, кнопкою «Провести списання». Новий канал
        (``submit_request``) створює документ із власними рядками, і списання
        там -- це видача комірником, яка вішає на рядок партії, а з партій
        береться собівартість заходу. Легасі-списання таких рядків не
        створює: воно закриває документ, і собівартість зникає НАЗАВЖДИ
        (``issue()`` після цього неможливий). Тому для документа ІПРМ не
        пропонує ні списання, ні коригування, ні редагування утримань.

        Ознака -- ДВІ, і обидві потрібні. ``quantity_requested`` приходить
        лише в новому payload, тож непорожнє значення однозначно вказує на
        документ. Але штовх статусу летить без ретраїв, і рядки можуть
        відстати; SUBMITTED та ISSUED легасі-канал не виробляє взагалі, тож
        самого статусу вже досить. MM Medic про всяк випадок відмовляє й на
        своєму боці (``actuals_unsupported_for_document``) -- тут гейт для
        того, щоб людина не бачила кнопки, яка все одно не спрацює.
        """
        if self.status in (MaterialReservationStatus.SUBMITTED,
                           MaterialReservationStatus.ISSUED):
            return True
        return any(item.quantity_requested is not None for item in self.items)

    @property
    def origin_label(self):
        return MaterialReservationOrigin.LABELS.get(self.origin, self.origin)


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

    # Five quantities, one per step of the MM Medic lifecycle. The two legacy
    # columns keep their meaning so existing screens and sums need no rewrite:
    #   quantity_requested -- скільки просив тренер (подання)
    #   quantity_reserved  -- скільки погоджено й утримується (approve)
    #   quantity_issued    -- скільки фізично видано (issue)
    #   quantity_returned  -- скільки повернуто після заходу (complete)
    #   quantity_actual    -- скільки спожито = issued - returned
    quantity_requested = db.Column(db.Integer, nullable=True)
    quantity_reserved = db.Column(db.Integer, nullable=False, default=0)
    quantity_issued = db.Column(db.Integer, nullable=True)
    quantity_returned = db.Column(db.Integer, nullable=True)
    quantity_actual = db.Column(db.Integer, nullable=True)

    # Гривнева вартість спожитого по цьому рядку, як її порахував MM Medic:
    # (видано - повернено) * ціна партії, підсумовано по партіях видачі.
    #
    # NULL != 0. NULL -- «оцінити нічим»: партій ще немає (документ до
    # відвантаження) або в жодної з них не було ціни. Нуль -- «порахували,
    # вийшло нуль». У звіті перше має бути прочерком, друге -- нулем.
    cost_uah = db.Column(db.Numeric(12, 2), nullable=True)

    # Чи ВСІ партії рядка мали ціну. Має значення тільки разом із `cost_uah`:
    # доки вартості немає, писати сюди `false` означало б стверджувати
    # «собівартість неповна» там, де її ще просто не рахували.
    cost_complete = db.Column(db.Boolean, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('reservation_id', 'sku', name='uq_material_item_sku'),
    )
