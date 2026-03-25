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


def upload_course_image(file, slug):
    """Save an uploaded course image and return its URL.

    Args:
        file: Werkzeug FileStorage object.
        slug: Course slug for directory naming.

    Returns:
        (url, error) tuple. url is None if error occurred.
    """
    if not file or not file.filename:
        return None, 'Файл не вибрано'

    if not allowed_file(file.filename):
        return None, 'Дозволені формати: PNG, JPG, JPEG, WebP'

    if not slug:
        return None, 'Slug курсу не вказано'

    ext = file.filename.rsplit('.', 1)[1].lower()
    safe_slug = secure_filename(slug)
    filename = f'{uuid4().hex[:8]}.{ext}'

    upload_dir = os.path.join(
        current_app.config['UPLOAD_FOLDER'], 'courses', safe_slug,
    )
    os.makedirs(upload_dir, exist_ok=True)

    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    url = f'/static/images/courses/{safe_slug}/{filename}'
    logger.info('Uploaded course image: %s', url)

    return url, None
