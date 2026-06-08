"""BlogPost -- допис блогу (дайджест заходу тощо).

Контент -- упорядкований список типізованих блоків у JSON-полі `content`
(розвиток патерну ProgramBlock): кожен блок -- dict {id, type, data}.
Рендер блоків -- серверний (Jinja-partial на тип). Вільні публікації:
прив'язки до конкретного заходу немає.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow


class BlogPost(TimestampMixin, db.Model):
    __tablename__ = 'blog_posts'

    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED)

    id = db.Column(BigIntPK, primary_key=True)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    excerpt = db.Column(db.String(500))
    cover_image = db.Column(db.String(500))

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
    def is_published(self):
        return self.status == self.STATUS_PUBLISHED and self.published_at is not None

    @property
    def approved_comment_count(self):
        from app.models.blog_comment import BlogComment
        from sqlalchemy import func
        return (
            db.session.query(func.count(BlogComment.id))
            .filter(
                BlogComment.post_id == self.id,
                BlogComment.status == BlogComment.STATUS_APPROVED,
            )
            .scalar()
        )

    def __repr__(self):
        return f'<BlogPost {self.slug}>'
