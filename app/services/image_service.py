"""Обробка завантажених зображень для блогу.

Приймає PNG/JPG/WebP та HEIC/HEIF (фото з iPhone), застосовує EXIF-орієнтацію,
конвертує у WebP і генерує дві версії: full (<=1600px) та thumbnail (<=400px).
Зберігає у app/static/images/blog/{slug}/ і повертає публічні URL.

Публічний API:
  * process_blog_image(file, slug) -> (dict|None, error|None)
        dict = {'url', 'thumb', 'width', 'height'}
  * ALLOWED_EXTENSIONS
"""
import logging
import os
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'heic', 'heif'}

_FULL_MAX = 1600     # макс. сторона повної версії, px
_THUMB_MAX = 400     # макс. сторона мініатюри, px
_FULL_QUALITY = 82
_THUMB_QUALITY = 80

# Реєструємо HEIF-декодер один раз. pillow-heif постачає libheif у колесі,
# тож імпорт безпечний; але про всяк випадок не валимо модуль, якщо його нема.
try:  # noqa: WPS229
    from pillow_heif import register_heif_opener
    register_heif_opener()
    _HEIF_OK = True
except Exception:  # pragma: no cover
    _HEIF_OK = False
    logger.warning('pillow-heif unavailable -- HEIC uploads will be rejected')


def _ext(filename):
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''


def allowed_file(filename):
    return _ext(filename) in ALLOWED_EXTENSIONS


def _fit(img, max_dim):
    """Зменшити до max_dim по більшій стороні (без збільшення)."""
    from PIL import Image
    w, h = img.size
    scale = min(1.0, max_dim / float(max(w, h)))
    if scale < 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    return img


def _normalize(img):
    """EXIF-орієнтація + режим, придатний для WebP (зберігаємо альфу)."""
    from PIL import ImageOps
    img = ImageOps.exif_transpose(img)
    if img.mode in ('RGBA', 'LA', 'P'):
        return img.convert('RGBA')
    return img.convert('RGB')


def process_blog_image(file, slug):
    """Зберегти завантажене зображення як WebP (full + thumb) під blog/{slug}/.

    Повертає (dict, None) при успіху або (None, error) при помилці.
    """
    if not file or not file.filename:
        return None, 'Файл не вибрано'
    if not allowed_file(file.filename):
        return None, 'Дозволені формати: PNG, JPG, JPEG, WebP, HEIC'
    if _ext(file.filename) in ('heic', 'heif') and not _HEIF_OK:
        return None, 'HEIC не підтримується на сервері (немає pillow-heif)'
    if not slug:
        slug = 'post'

    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(file.stream)
        img = _normalize(img)
    except (UnidentifiedImageError, OSError) as exc:
        logger.warning('Bad image upload (%s): %s', file.filename, exc)
        return None, 'Не вдалося прочитати зображення'

    safe_slug = secure_filename(slug) or 'post'
    base = uuid4().hex[:12]
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'blog', safe_slug)
    os.makedirs(upload_dir, exist_ok=True)

    full = _fit(img, _FULL_MAX)
    thumb = _fit(img, _THUMB_MAX)

    full_name = f'{base}.webp'
    thumb_name = f'{base}_thumb.webp'
    full.save(os.path.join(upload_dir, full_name), 'WEBP', quality=_FULL_QUALITY, method=6)
    thumb.save(os.path.join(upload_dir, thumb_name), 'WEBP', quality=_THUMB_QUALITY, method=6)

    rel = f'/static/images/blog/{safe_slug}'
    logger.info('Blog image saved: %s/%s (%dx%d)', rel, full_name, full.width, full.height)
    return {
        'url': f'{rel}/{full_name}',
        'thumb': f'{rel}/{thumb_name}',
        'width': full.width,
        'height': full.height,
    }, None
