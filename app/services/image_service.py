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
_SIGN_MAX = 1200     # макс. сторона підпису, px (друкується на сертифікаті ~40 мм)
_SIGN_QUALITY = 90   # вище звичайного: тонкі лінії пера не прощають артефактів

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


def _validate_upload(file):
    """Спільна валідація завантаження. Повертає текст помилки або None."""
    if not file or not file.filename:
        return 'Файл не вибрано'
    if not allowed_file(file.filename):
        return 'Дозволені формати: PNG, JPG, JPEG, WebP, HEIC'
    if _ext(file.filename) in ('heic', 'heif') and not _HEIF_OK:
        return 'HEIC не підтримується на сервері (немає pillow-heif)'
    return None


def _save_processed(file, rel_dir):
    """Обробити й зберегти WebP (full + thumb) під images/{rel_dir}/.

    rel_dir -- posix-шлях відносно app/static/images (напр. 'blog/my-slug'
    або 'trainers/x/certificates'). Повертає (dict, None) або (None, error).
    """
    from PIL import Image, UnidentifiedImageError

    base = uuid4().hex[:12]
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], *rel_dir.split('/'))
    full_name = f'{base}.webp'
    thumb_name = f'{base}_thumb.webp'

    # Уся обробка під try: open/normalize можуть кинути DecompressionBombError
    # (величезне/зловмисне зображення), а resize/save -- OSError. Будь-яка з них
    # без обробки давала б 500; повертаємо керовану помилку.
    try:
        img = _normalize(Image.open(file.stream))
        full = _fit(img, _FULL_MAX)
        thumb = _fit(img, _THUMB_MAX)
        os.makedirs(upload_dir, exist_ok=True)
        full.save(os.path.join(upload_dir, full_name), 'WEBP', quality=_FULL_QUALITY, method=6)
        thumb.save(os.path.join(upload_dir, thumb_name), 'WEBP', quality=_THUMB_QUALITY, method=6)
    except Image.DecompressionBombError as exc:
        logger.warning('Image too large (%s): %s', file.filename, exc)
        return None, 'Зображення завелике для обробки'
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning('Bad image upload (%s): %s', file.filename, exc)
        return None, 'Не вдалося прочитати зображення'
    except Exception:
        logger.exception('Unexpected error processing image %s', file.filename)
        return None, 'Помилка обробки зображення'

    rel = f'/static/images/{rel_dir}'
    logger.info('Image saved: %s/%s (%dx%d)', rel, full_name, full.width, full.height)
    return {
        'url': f'{rel}/{full_name}',
        'thumb': f'{rel}/{thumb_name}',
        'width': full.width,
        'height': full.height,
    }, None


def process_blog_image(file, slug):
    """WebP (full + thumb) під blog/{slug}/. Повертає (dict, None) або (None, error)."""
    err = _validate_upload(file)
    if err:
        return None, err
    safe_slug = secure_filename(slug or '') or 'post'
    return _save_processed(file, f'blog/{safe_slug}')


def process_trainer_certificate(file, slug):
    """WebP (full + thumb) під trainers/{slug}/certificates/ (захищено в деплої)."""
    err = _validate_upload(file)
    if err:
        return None, err
    safe_slug = secure_filename(slug or '') or 'trainer'
    return _save_processed(file, f'trainers/{safe_slug}/certificates')


def process_trainer_signature(file, slug):
    """Підпис тренера -> images/trainers/{slug}/{slug}_signature.webp.

    Ім'я детерміноване (без uuid): повторне завантаження перезаписує підпис
    того самого тренера, а не плодить сиріт. Файл лежить у static, бо
    сертифікати рендерить WeasyPrint із base_url=static_folder і
    Trainer.signature зберігає саме такий відносний шлях (не /media/).
    Прозорість зберігається (_normalize -> RGBA), без thumb: підпис і так
    маленький. Повертає ({path, url, width, height}, None) або (None, error).
    """
    err = _validate_upload(file)
    if err:
        return None, err

    from PIL import Image, UnidentifiedImageError

    safe_slug = secure_filename(slug or '') or 'trainer'
    rel_dir = f'trainers/{safe_slug}'
    name = f'{safe_slug}_signature.webp'
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], *rel_dir.split('/'))
    abs_path = os.path.join(upload_dir, name)

    try:
        img = _fit(_normalize(Image.open(file.stream)), _SIGN_MAX)
        os.makedirs(upload_dir, exist_ok=True)
        img.save(abs_path, 'WEBP', quality=_SIGN_QUALITY, method=6)
    except Image.DecompressionBombError as exc:
        logger.warning('Signature image too large (%s): %s', file.filename, exc)
        return None, 'Зображення завелике для обробки'
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning('Bad signature upload (%s): %s', file.filename, exc)
        return None, 'Не вдалося прочитати зображення'
    except Exception:
        logger.exception('Unexpected error processing signature %s', file.filename)
        return None, 'Помилка обробки зображення'

    rel = f'images/{rel_dir}/{name}'
    logger.info('Trainer signature saved: %s (%dx%d)', rel, img.width, img.height)
    # url -- лише для прев'ю в адмінці; ?v збиває кеш браузера, бо ім'я файлу
    # при перезавантаженні підпису не змінюється. У БД пишеться чистий path.
    return {
        'path': rel,
        'url': f'/static/{rel}?v={int(os.path.getmtime(abs_path))}',
        'width': img.width,
        'height': img.height,
    }, None
