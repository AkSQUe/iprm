import os
import logging
from uuid import uuid4
from flask import request, jsonify, current_app
from werkzeug.utils import secure_filename
from app.admin import admin_bp
from app.admin.decorators import admin_required

audit_logger = logging.getLogger('audit')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@admin_bp.route('/upload/course-image', methods=['POST'])
@admin_required
def upload_course_image():
    """Завантаження зображення курсу у images/courses/{slug}/"""
    file = request.files.get('file')
    slug = request.form.get('slug', '').strip()

    if not file or not file.filename:
        return jsonify({'error': 'Файл не вибрано'}), 400

    if not _allowed_file(file.filename):
        return jsonify({'error': 'Дозволені формати: PNG, JPG, JPEG, WebP'}), 400

    if not slug:
        return jsonify({'error': 'Slug курсу не вказано'}), 400

    # Безпечне ім'я файлу з унікальним префіксом
    ext = file.filename.rsplit('.', 1)[1].lower()
    safe_slug = secure_filename(slug)
    filename = f'{uuid4().hex[:8]}.{ext}'

    # Створюємо директорію
    upload_dir = os.path.join(
        current_app.config['UPLOAD_FOLDER'], 'courses', safe_slug
    )
    os.makedirs(upload_dir, exist_ok=True)

    # Зберігаємо файл
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    # URL для відображення
    url = f'/static/images/courses/{safe_slug}/{filename}'

    audit_logger.info('Uploaded course image: %s', url)

    return jsonify({'url': url}), 200
