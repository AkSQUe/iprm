"""MaterialKit -- стандартний набір матеріалів під курс.

Сьогодні такі списки живуть на боці MM Medic і тягнуться через partner API
на кожен захід. Вони переїжджають сюди, бо саме ІПРМ знає, який набір
відповідає якому курсу; MM Medic лишається складом, що виконує заявку
(app.models.material_reservation), а не джерелом правди про її вміст.
Віддалений fetch лишається живим, доки його не заберуть окремим планом --
це поза межами цієї моделі.

`course_id` навмисно NULLABLE: NULL означає "універсальний комплект",
доступний БУДЬ-ЯКОМУ курсу. Дешевше за окрему таблицю глобальних наборів і
не додає другої гілки в коді підбору комплекту.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class MaterialKit(TimestampMixin, db.Model):
    """Заголовок: один комплект (набір позицій), опційно прив'язаний до курсу."""
    __tablename__ = 'material_kits'

    id = db.Column(BigIntPK, primary_key=True)
    course_id = db.Column(
        db.BigInteger,
        db.ForeignKey('courses.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    name = db.Column(db.String(200), nullable=False)
    is_default = db.Column(db.Boolean, nullable=False, default=False,
                           server_default=db.false())
    is_active = db.Column(db.Boolean, nullable=False, default=True,
                          server_default=db.true())
    notes = db.Column(db.Text, nullable=True)

    # NB: без 'delete-orphan' на backref'і. course_id навмисно nullable
    # (NULL = універсальний комплект, доступний будь-якому курсу -- див.
    # докстрінг модуля); 'delete-orphan' трактував би `kit.course = None`
    # як "набір-сирота" і видаляв його разом з items, хоча це легітимний
    # спосіб зробити набір універсальним. Видалення курсу і так каскадує на
    # рівні БД через ondelete='CASCADE' на FK нижче -- нічого не втрачається.
    course = db.relationship('Course', backref=db.backref(
        'material_kits', lazy='selectin',
    ))
    items = db.relationship(
        'MaterialKitItem',
        backref='kit',
        lazy='selectin',
        cascade='all, delete-orphan',
        order_by='MaterialKitItem.sku',
    )

    def __repr__(self):
        return f'<MaterialKit {self.name!r} course_id={self.course_id}>'


class MaterialKitItem(db.Model):
    """Рядок: одна позиція комплекту, зі снапшотом назви на момент додавання."""
    __tablename__ = 'material_kit_items'

    id = db.Column(BigIntPK, primary_key=True)
    kit_id = db.Column(
        db.BigInteger,
        db.ForeignKey('material_kits.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    sku = db.Column(db.String(100), nullable=False)
    name_snapshot = db.Column(db.String(255), nullable=True)
    # CHECK > 0: нуль -- це позиція, яку застосування комплекту мовчки
    # пропустить, і різницю між "не поклали" і "поклали нуль" ніхто не
    # побачить. Якщо позицію не потрібно класти -- її не додають у комплект.
    quantity = db.Column(db.Integer, nullable=False)
    is_required = db.Column(db.Boolean, nullable=False, default=False,
                            server_default=db.false())
    note = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('kit_id', 'sku', name='uq_material_kit_items_kit_sku'),
        db.CheckConstraint('quantity > 0', name='ck_material_kit_items_quantity_positive'),
    )

    def __repr__(self):
        return f'<MaterialKitItem {self.sku!r} qty={self.quantity} kit_id={self.kit_id}>'
