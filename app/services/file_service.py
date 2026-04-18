"""File upload service."""
import os
import logging
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


def allowed_file(filename):
    """Check if filename has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _upload_image(file, slug, subdir, slug_error):
    """Shared helper: save uploaded image under images/{subdir}/{slug}/ and return URL."""
    if not file or not file.filename:
        return None, 'Файл не вибрано'

    if not allowed_file(file.filename):
        return None, 'Дозволені формати: PNG, JPG, JPEG, WebP'

    if not slug:
        return None, slug_error

    ext = file.filename.rsplit('.', 1)[1].lower()
    safe_slug = secure_filename(slug)
    filename = f'{uuid4().hex[:8]}.{ext}'

    upload_dir = os.path.join(
        current_app.config['UPLOAD_FOLDER'], subdir, safe_slug,
    )
    os.makedirs(upload_dir, exist_ok=True)

    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    url = f'/static/images/{subdir}/{safe_slug}/{filename}'
    logger.info('Uploaded %s image: %s', subdir, url)

    return url, None


def upload_course_image(file, slug):
    """Save an uploaded course image to images/courses/{slug}/ and return its URL."""
    return _upload_image(file, slug, 'courses', 'Slug курсу не вказано')


def upload_trainer_image(file, slug):
    """Save an uploaded trainer photo to images/trainers/{slug}/ and return its URL."""
    return _upload_image(file, slug, 'trainers', 'Slug тренера не вказано')
