"""MediaFile -- централізований реєстр медіа-файлів.

Один запис на кожен завантажений файл. Поліморфна прив'язка до будь-якої
сутності через (entity_type, entity_id, usage_type). Фізично файли лежать
ПОЗА app/static -- у MEDIA_FOLDER (durable через деплой), віддаються за
префіксом MEDIA_URL_PREFIX (/media/...). Responsive-варіанти (лише WebP)
зберігаються у responsive_variants як {context: relative_path}.

Створення/обробка файлів -- у app.services.media_service (модель тримає лише
дані + запити + побудову URL).
"""
import os
import mimetypes

from flask import current_app

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class MediaFile(TimestampMixin, db.Model):
    __tablename__ = 'media_files'

    USAGE_TYPES = (
        'main', 'gallery', 'cover', 'certificate', 'patent',
        'inline', 'photo', 'hero', 'card', 'document',
    )

    id = db.Column(BigIntPK, primary_key=True)
    uploaded_by = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True, index=True,
    )

    filename = db.Column(db.String(255), nullable=False)        # збережене ім'я (uuid.webp)
    original_name = db.Column(db.String(255))                   # оригінальна назва
    file_path = db.Column(db.String(500), nullable=False)       # відносно MEDIA_FOLDER (posix), напр. 2026/06/uuid.webp
    mime_type = db.Column(db.String(100), nullable=False, default='application/octet-stream')
    file_size = db.Column(db.BigInteger, nullable=False, default=0)

    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    alt_text = db.Column(db.String(255))

    # Поліморфна прив'язка
    entity_type = db.Column(db.String(50), index=True)          # blog_post, trainer, course
    entity_id = db.Column(db.BigInteger, index=True)
    usage_type = db.Column(db.String(50), nullable=False, default='main', index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    # Responsive WebP-варіанти: {context: 'relative/path.webp'} відносно MEDIA_FOLDER
    responsive_variants = db.Column(db.JSON, nullable=False, default=dict)

    uploader = db.relationship('User', foreign_keys=[uploaded_by])

    __table_args__ = (
        db.Index('ix_media_entity_usage_active', 'entity_type', 'entity_id', 'usage_type', 'is_active'),
        db.CheckConstraint('file_size >= 0', name='ck_media_files_size_non_negative'),
    )

    # ---- Властивості ----
    @property
    def is_image(self):
        return bool(self.mime_type) and self.mime_type.startswith('image/')

    @property
    def abs_path(self):
        """Абсолютний шлях до файлу на диску."""
        base = current_app.config['MEDIA_FOLDER']
        return os.path.join(base, *self.file_path.split('/'))

    @property
    def url(self):
        """Публічний URL основного файлу (/media/{file_path})."""
        prefix = current_app.config.get('MEDIA_URL_PREFIX', '/media')
        return f'{prefix}/{self.file_path}'

    def variant_url(self, context):
        """URL WebP-варіанту для контексту; fallback -- основний файл."""
        path = (self.responsive_variants or {}).get(context)
        if not path:
            return self.url
        prefix = current_app.config.get('MEDIA_URL_PREFIX', '/media')
        return f'{prefix}/{path}'

    # ---- Запити ----
    @classmethod
    def for_entity(cls, entity_type, entity_id, usage_type=None):
        q = cls.query.filter_by(
            entity_type=entity_type, entity_id=entity_id, is_active=True,
        )
        if usage_type:
            q = q.filter_by(usage_type=usage_type)
        return q.order_by(cls.sort_order.asc(), cls.id.asc())

    @classmethod
    def main_for(cls, entity_type, entity_id, usage_type='main'):
        return cls.for_entity(entity_type, entity_id, usage_type).first()

    def __repr__(self):
        return f'<MediaFile {self.id} {self.entity_type}:{self.entity_id}/{self.usage_type}>'

    @staticmethod
    def guess_mime(filename):
        return mimetypes.guess_type(filename or '')[0] or 'application/octet-stream'
