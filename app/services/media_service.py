"""Сервіс медіа-реєстру: обробка завантажень у MEDIA_FOLDER + WebP-варіанти.

Файли лежать поза app/static (durable), за схемою:
  {MEDIA_FOLDER}/{рік}/{міс}/{uuid}.webp                     -- основний (<=1600px)
  {MEDIA_FOLDER}/{рік}/{міс}/variants/{context}/{uuid}_{context}.webp

Лише WebP (рішення проєкту). HEIC/JPG/PNG конвертуються. Метадані -> MediaFile.
PIL-хелпери (нормалізація EXIF/режиму, fit) переюзовуємо з image_service.
"""
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.media_file import MediaFile
from app.services.image_service import (
    ALLOWED_EXTENSIONS, _normalize, _fit, _ext, _HEIF_OK,
)

logger = logging.getLogger(__name__)

# Responsive-контексти (лише WebP). Значення -- макс. сторона у px.
_FULL_MAX = 1600
_CONTEXTS = {'thumb': 400, 'card': 800}
_QUALITY = 82


def _media_root():
    return current_app.config['MEDIA_FOLDER']


def _save_webp(img, abs_path, max_dim):
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    _fit(img, max_dim).save(abs_path, 'WEBP', quality=_QUALITY, method=6)


def create_from_upload(file, *, entity_type=None, entity_id=None,
                       usage_type='main', alt_text=None, uploader_id=None,
                       sort_order=0):
    """Зберегти завантажений файл як WebP (+варіанти) і створити MediaFile.

    Повертає (MediaFile, None) при успіху або (None, error)."""
    if not file or not file.filename:
        return None, 'Файл не вибрано'
    ext = _ext(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        return None, 'Дозволені формати: PNG, JPG, JPEG, WebP, HEIC'
    if ext in ('heic', 'heif') and not _HEIF_OK:
        return None, 'HEIC не підтримується на сервері (немає pillow-heif)'

    from PIL import Image, UnidentifiedImageError

    now = datetime.now(timezone.utc)
    rel_dir = f'{now.year}/{now.month:02d}'
    base = uuid4().hex[:12]
    filename = f'{base}.webp'
    file_rel = f'{rel_dir}/{filename}'
    root = _media_root()

    try:
        img = _normalize(Image.open(file.stream))
        _save_webp(img, os.path.join(root, *file_rel.split('/')), _FULL_MAX)
        variants = {}
        for ctx, dim in _CONTEXTS.items():
            v_rel = f'{rel_dir}/variants/{ctx}/{base}_{ctx}.webp'
            _save_webp(img, os.path.join(root, *v_rel.split('/')), dim)
            variants[ctx] = v_rel
        full = _fit(img, _FULL_MAX)
        width, height = full.width, full.height
    except Image.DecompressionBombError as exc:
        logger.warning('Media image too large (%s): %s', file.filename, exc)
        return None, 'Зображення завелике для обробки'
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning('Bad media upload (%s): %s', file.filename, exc)
        return None, 'Не вдалося прочитати зображення'
    except Exception:
        logger.exception('Unexpected error processing media %s', file.filename)
        return None, 'Помилка обробки зображення'

    size = os.path.getsize(os.path.join(root, *file_rel.split('/')))
    media = MediaFile(
        uploaded_by=uploader_id,
        filename=filename,
        original_name=(file.filename or '')[:255],
        file_path=file_rel,
        mime_type='image/webp',
        file_size=size,
        width=width,
        height=height,
        alt_text=(alt_text or None),
        entity_type=entity_type,
        entity_id=entity_id,
        usage_type=usage_type,
        sort_order=sort_order,
        responsive_variants=variants,
    )
    db.session.add(media)
    db.session.flush()
    logger.info('MediaFile %s created: %s (%dx%d)', media.id, file_rel, width, height)
    return media, None


def delete_media(media):
    """Видалити фізичні файли (основний + варіанти) і запис MediaFile."""
    root = _media_root()
    paths = [media.file_path] + list((media.responsive_variants or {}).values())
    for rel in paths:
        try:
            ap = os.path.join(root, *rel.split('/'))
            if os.path.exists(ap):
                os.remove(ap)
        except OSError:
            logger.warning('Failed to delete media file %s', rel)
    db.session.delete(media)
