"""BlogPost -- допис блогу (дайджест заходу тощо).

Контент -- упорядкований список типізованих блоків у JSON-полі `content`
(розвиток патерну ProgramBlock): кожен блок -- dict {id, type, data}.
Рендер блоків -- серверний (Jinja-partial на тип). Вільні публікації:
прив'язки до конкретного заходу немає.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, TranslatableMixin, BigIntPK, utcnow


class BlogPost(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'blog_posts'
    __translatable__ = ('title', 'excerpt', 'content', 'meta_title', 'meta_description')

    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED)

    # Див. коментар у BlogComment: та сама вада, той самий спосіб.
    STATUS_LABELS = {
        STATUS_DRAFT: 'Чернетка',
        STATUS_PUBLISHED: 'Опубліковано',
    }
    STATUS_BADGES = {
        STATUS_DRAFT: 'draft',
        STATUS_PUBLISHED: 'active',
    }

    id = db.Column(BigIntPK, primary_key=True)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    excerpt = db.Column(db.String(500))
    # Обкладинка -- лише через медіа-реєстр (Фаза 6: legacy cover_image прибрано).
    cover_media_id = db.Column(
        db.BigInteger,
        db.ForeignKey('media_files.id', ondelete='SET NULL'),
        nullable=True,
    )

    # Упорядкований список блоків: [{'id', 'type', 'data': {...}}, ...]
    content = db.Column(db.JSON, nullable=False, default=list)

    status = db.Column(db.String(20), nullable=False, default=STATUS_DRAFT, index=True)
    published_at = db.Column(db.DateTime(timezone=True), index=True)

    author_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    # SEO
    meta_title = db.Column(db.String(200))
    meta_description = db.Column(db.String(500))

    views = db.Column(db.Integer, nullable=False, default=0)

    author = db.relationship('User', foreign_keys=[author_id])
    cover_media = db.relationship('MediaFile', foreign_keys=[cover_media_id])
    comments = db.relationship(
        'BlogComment',
        back_populates='post',
        cascade='all, delete-orphan',
        order_by='BlogComment.created_at',
        passive_deletes=True,
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft', 'published')",
            name='ck_blog_posts_status',
        ),
        # Лістинг опублікованих за датою (DESC сортуємо у запиті).
        db.Index('ix_blog_posts_status_published', 'status', 'published_at'),
    )

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_badge(self):
        """Модифікатор `.badge--*` під поточний стан (див. STATUS_BADGES)."""
        return self.STATUS_BADGES.get(self.status, 'draft')

    @property
    def is_published(self):
        return self.status == self.STATUS_PUBLISHED and self.published_at is not None

    @property
    def cover_src(self):
        """URL обкладинки для тегу <img src> (середній варіант). None, якщо немає."""
        return self.cover_media.variant_url('card') if self.cover_media else None

    @property
    def cover_full(self):
        """URL повнорозмірної обкладинки (для og:image / srcset 1600w)."""
        return self.cover_media.url if self.cover_media else None

    def __repr__(self):
        return f'<BlogPost {self.slug}>'
