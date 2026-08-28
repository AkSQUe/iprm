"""BlogComment -- коментар до допису блогу.

Анонімні коментарі (ім'я + email, email не публікується). Премодерація:
новий коментар створюється у статусі 'pending' і показується публічно лише
після 'approved'. Підтримка гілок: self-FK parent_id (відповіді на коментарі).
"""
from app.extensions import db
from app.models.mixins import BigIntPK, SoftDeleteMixin, TimestampMixin


class BlogComment(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = 'blog_comments'

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_SPAM = 'spam'
    STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_SPAM)

    # Підпис і модифікатор `.badge--*` на кожен стан. Тримається тут, а не
    # тернарником у розмітці: там він писав `admin-badge--success`, класу
    # з таким іменем у системі немає взагалі, і плашка виходила голим
    # текстом -- у реєстрі коментарів колонка «Статус» була просто словом.
    STATUS_LABELS = {
        STATUS_PENDING: 'На модерації',
        STATUS_APPROVED: 'Схвалено',
        STATUS_SPAM: 'Спам',
    }
    STATUS_BADGES = {
        STATUS_PENDING: 'pending',
        STATUS_APPROVED: 'active',
        STATUS_SPAM: 'cancelled',
    }

    # Максимальна глибина вкладеності гілок (0 -- кореневий коментар).
    MAX_DEPTH = 3

    id = db.Column(BigIntPK, primary_key=True)
    post_id = db.Column(
        db.BigInteger,
        db.ForeignKey('blog_posts.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    parent_id = db.Column(
        db.BigInteger,
        db.ForeignKey('blog_comments.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )

    author_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255))  # не публікується; для звʼязку/анти-спаму
    body = db.Column(db.Text, nullable=False)

    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING, index=True)
    ip = db.Column(db.String(45))  # IPv4/IPv6

    post = db.relationship('BlogPost', back_populates='comments')
    parent = db.relationship(
        'BlogComment',
        remote_side=[id],
        back_populates='replies',
    )
    replies = db.relationship(
        'BlogComment',
        back_populates='parent',
        cascade='all, delete-orphan',
        order_by='BlogComment.created_at',
        passive_deletes=True,
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'approved', 'spam')",
            name='ck_blog_comments_status',
        ),
        db.Index('ix_blog_comments_post_status', 'post_id', 'status'),
    )

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_badge(self):
        """Модифікатор `.badge--*` під поточний стан (див. STATUS_BADGES)."""
        return self.STATUS_BADGES.get(self.status, 'draft')

    @property
    def is_approved(self):
        return self.status == self.STATUS_APPROVED

    def __repr__(self):
        return f'<BlogComment {self.id} post={self.post_id} {self.status}>'
