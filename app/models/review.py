"""Відгуки випускників (публічний блок "Після навчання" на Головній).

Адмін веде відгуки вручну (CRUD); публікуються лише is_published. Поки реальних
відгуків нема -- на Головній показуємо хардкод-заглушку (див. шаблон home.html).
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class Review(TimestampMixin, db.Model):
    __tablename__ = 'reviews'

    id = db.Column(BigIntPK, primary_key=True)

    author_name = db.Column(db.String(120), nullable=False)
    # Роль/спеціальність (напр. "лікарка-косметологиня") і місто -- показуємо
    # у підписі. Обидва опційні.
    author_role = db.Column(db.String(160))
    city = db.Column(db.String(120))

    text = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, nullable=False, default=5)

    is_published = db.Column(db.Boolean, default=False, nullable=False, index=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    # Опційна прив'язка до курсу (для контексту, не обов'язково).
    course_id = db.Column(
        db.BigInteger, db.ForeignKey('courses.id', ondelete='SET NULL'), nullable=True,
    )
    course = db.relationship('Course')

    __table_args__ = (
        db.CheckConstraint('rating >= 1 AND rating <= 5', name='ck_reviews_rating'),
        db.Index('ix_reviews_published_sort', 'is_published', 'sort_order'),
    )

    @classmethod
    def published(cls, limit=6):
        """Опубліковані відгуки для публічного блоку (найновіші/за порядком)."""
        return cls.query.filter_by(is_published=True).order_by(
            cls.sort_order, cls.created_at.desc(),
        ).limit(limit).all()

    @property
    def byline(self):
        """Підпис "Ім'я · Місто · Роль" (пропускає порожні частини)."""
        return ' · '.join(p for p in (self.author_name, self.city, self.author_role) if p)

    def __repr__(self):
        return f'<Review {self.author_name} {self.rating}*>'
