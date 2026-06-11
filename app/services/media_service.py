"""Сервіс медіа-реєстру: обробка завантажень у MEDIA_FOLDER + WebP-варіанти.

Файли лежать поза app/static (durable), за схемою:
  {MEDIA_FOLDER}/{рік}/{міс}/{uuid}.webp                     -- основний (<=1600px)
  {MEDIA_FOLDER}/{рік}/{міс}/variants/{context}/{uuid}_{context}.webp

Лише WebP (рішення проєкту). HEIC/JPG/PNG конвертуються. Метадані -> MediaFile.
PIL-хелпери (нормалізація EXIF/режиму, fit) переюзовуємо з image_service.
"""
import logging
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

from flask import current_app

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
    """Зберегти зменшену копію у WebP; повертає fitted-зображення (для розмірів)."""
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    fitted = _fit(img, max_dim)
    fitted.save(abs_path, 'WEBP', quality=_QUALITY, method=6)
    return fitted


def _ingest_image(img, *, original_name, entity_type, entity_id, usage_type,
                  alt_text, uploader_id, sort_order):
    """Зберегти PIL-зображення як WebP (основний + варіанти) і створити MediaFile.

    Спільне ядро для create_from_upload та create_from_path. `img` має бути вже
    нормалізованим (EXIF/режим). Кидає винятки PIL/OS нагору -- викликач ловить.
    Повертає MediaFile (flushed, без commit)."""
    now = datetime.now(timezone.utc)
    rel_dir = f'{now.year}/{now.month:02d}'
    base = uuid4().hex[:12]
    filename = f'{base}.webp'
    file_rel = f'{rel_dir}/{filename}'
    root = _media_root()

    full = _save_webp(img, os.path.join(root, *file_rel.split('/')), _FULL_MAX)
    width, height = full.width, full.height
    variants = {}
    for ctx, dim in _CONTEXTS.items():
        v_rel = f'{rel_dir}/variants/{ctx}/{base}_{ctx}.webp'
        _save_webp(img, os.path.join(root, *v_rel.split('/')), dim)
        variants[ctx] = v_rel

    size = os.path.getsize(os.path.join(root, *file_rel.split('/')))
    media = MediaFile(
        uploaded_by=uploader_id,
        filename=filename,
        original_name=(original_name or '')[:255],
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
    return media


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

    try:
        img = _normalize(Image.open(file.stream))
        media = _ingest_image(
            img, original_name=file.filename, entity_type=entity_type,
            entity_id=entity_id, usage_type=usage_type, alt_text=alt_text,
            uploader_id=uploader_id, sort_order=sort_order,
        )
    except Image.DecompressionBombError as exc:
        logger.warning('Media image too large (%s): %s', file.filename, exc)
        return None, 'Зображення завелике для обробки'
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning('Bad media upload (%s): %s', file.filename, exc)
        return None, 'Не вдалося прочитати зображення'
    except Exception:
        logger.exception('Unexpected error processing media %s', file.filename)
        return None, 'Помилка обробки зображення'

    return media, None


def create_from_path(src_abs, *, original_name=None, entity_type=None,
                     entity_id=None, usage_type='main', alt_text=None,
                     uploader_id=None, sort_order=0):
    """Створити MediaFile з наявного файлу на диску (для міграції даних).

    На відміну від create_from_upload, читає файл за абсолютним шляхом, а не з
    HTTP-стріму. Повертає (MediaFile, None) або (None, error)."""
    if not src_abs or not os.path.isfile(src_abs):
        return None, f'Файл не знайдено: {src_abs}'

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(src_abs) as raw:
            img = _normalize(raw)
            media = _ingest_image(
                img, original_name=(original_name or os.path.basename(src_abs)),
                entity_type=entity_type, entity_id=entity_id,
                usage_type=usage_type, alt_text=alt_text,
                uploader_id=uploader_id, sort_order=sort_order,
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning('Bad source image for migration (%s): %s', src_abs, exc)
        return None, 'Не вдалося прочитати зображення'
    except Exception:
        logger.exception('Unexpected error migrating media %s', src_abs)
        return None, 'Помилка обробки зображення'

    return media, None


def _safe_slug(value, maxlen=60):
    """Звести довільний slug/назву до безпечного для імені файлу токена."""
    s = re.sub(r'[^a-z0-9]+', '-', (value or '').lower()).strip('-')
    s = s[:maxlen].rstrip('-')
    return s or 'media'


def friendly_basename(slug, usage_type, index=None):
    """Людиночитна основа імені файлу: {slug}-{usage}[-{index}] (без розширення)."""
    base = f'{_safe_slug(slug)}-{usage_type}'
    if index is not None:
        base = f'{base}-{index}'
    return base


def _media_url(rel_path):
    prefix = current_app.config.get('MEDIA_URL_PREFIX', '/media')
    return f'{prefix}/{rel_path}'


def _join(rel_dir, name):
    return f'{rel_dir}/{name}' if rel_dir else name


def rename_for_entity(media, slug, index=None):
    """Перейменувати фізичні файли media у читабельну схему {slug}-{usage}[-N].

    Перейменовує основний файл + усі responsive-варіанти у тій самій теці,
    оновлює media.file_path / responsive_variants. Ідемпотентно (якщо ім'я вже
    збігається -> нічого не робить). Повертає dict {старий_url: новий_url} для
    оновлення посилань у JSON-полях (порожній, якщо без змін).

    Захищений: НЕ кидає винятків (щоб збій ФС не зривав збереження сутності і не
    лишав ФС↔БД у розсинхроні) і НЕ перезаписує чужий файл (no-clobber)."""
    root = _media_root()
    rel_dir = os.path.dirname(media.file_path) or ''
    name = friendly_basename(slug, media.usage_type, index)
    new_main = _join(rel_dir, f'{name}.webp')
    if new_main == media.file_path:
        return {}
    # Колізія -> унікалізуємо суфіксом id; якщо й це зайнято -- не чіпаємо (no-clobber).
    if os.path.exists(os.path.join(root, *new_main.split('/'))):
        name = f'{name}-{media.id}'
        new_main = _join(rel_dir, f'{name}.webp')
        if os.path.exists(os.path.join(root, *new_main.split('/'))):
            logger.warning('Skip rename media %s: target %s exists', media.id, new_main)
            return {}

    old_abs = os.path.join(root, *media.file_path.split('/'))
    new_abs = os.path.join(root, *new_main.split('/'))
    try:
        if os.path.exists(old_abs):
            os.rename(old_abs, new_abs)
    except OSError:
        logger.exception('Failed to rename media %s main file', media.id)
        return {}  # media лишається з поточним іменем -- ФС↔БД консистентні

    mapping = {_media_url(media.file_path): _media_url(new_main)}
    media.file_path = new_main

    new_variants = {}
    for ctx, vpath in (media.responsive_variants or {}).items():
        vdir = os.path.dirname(vpath) or ''
        nvp = _join(vdir, f'{name}_{ctx}.webp')
        vsrc = os.path.join(root, *vpath.split('/'))
        vdst = os.path.join(root, *nvp.split('/'))
        try:
            if os.path.exists(vsrc):
                os.rename(vsrc, vdst)
            mapping[_media_url(vpath)] = _media_url(nvp)
            new_variants[ctx] = nvp
        except OSError:
            logger.exception('Failed to rename media %s variant %s', media.id, ctx)
            new_variants[ctx] = vpath  # лишаємо стару назву -- шлях у БД = шлях на диску
    media.responsive_variants = new_variants
    logger.info('Renamed media %s -> %s', media.id, new_main)
    return mapping


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
