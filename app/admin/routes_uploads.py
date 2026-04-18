import logging
from flask import request, jsonify
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.services import file_service

audit_logger = logging.getLogger('audit')


@admin_bp.route('/upload/course-image', methods=['POST'])
@admin_required
def upload_course_image():
    """Upload a course image to images/courses/{slug}/."""
    file = request.files.get('file')
    slug = request.form.get('slug', '').strip()

    url, error = file_service.upload_course_image(file, slug)
    if error:
        return jsonify({'error': error}), 400

    audit_logger.info('Uploaded course image: %s', url)
    return jsonify({'url': url}), 200


@admin_bp.route('/upload/trainer-image', methods=['POST'])
@admin_required
def upload_trainer_image():
    """Upload a trainer photo to images/trainers/{slug}/."""
    file = request.files.get('file')
    slug = request.form.get('slug', '').strip()

    url, error = file_service.upload_trainer_image(file, slug)
    if error:
        return jsonify({'error': error}), 400

    audit_logger.info('Uploaded trainer image: %s', url)
    return jsonify({'url': url}), 200
