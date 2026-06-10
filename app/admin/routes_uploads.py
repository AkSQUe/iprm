import logging
from flask import request, jsonify
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.services import file_service
from app.services import image_service
from app.services import media_service

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


def _opt_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@admin_bp.route('/upload/media', methods=['POST'])
@admin_required
def upload_media():
    """Універсальне завантаження у медіа-реєстр (MediaFile).

    Приймає file + опційні entity_type/entity_id/usage_type/alt/sort_order.
    Конвертує у WebP (+варіанти), створює MediaFile. Повертає {id, url,
    variants, width, height, alt}.
    """
    from flask_login import current_user

    file = request.files.get('file')
    media, error = media_service.create_from_upload(
        file,
        entity_type=(request.form.get('entity_type') or None),
        entity_id=_opt_int(request.form.get('entity_id')),
        usage_type=(request.form.get('usage_type') or 'main'),
        alt_text=(request.form.get('alt') or None),
        uploader_id=current_user.id,
        sort_order=_opt_int(request.form.get('sort_order')) or 0,
    )
    if error:
        return jsonify({'error': error}), 400
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to persist uploaded media')
        return jsonify({'error': 'Помилка збереження'}), 500

    audit_logger.info('Uploaded media %s (%s)', media.id, media.file_path)
    return jsonify({
        'id': media.id,
        'url': media.url,
        'thumb': media.variant_url('thumb'),
        'card': media.variant_url('card'),
        'width': media.width,
        'height': media.height,
        'alt': media.alt_text or '',
    }), 200


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


@admin_bp.route('/upload/blog-image', methods=['POST'])
@admin_required
def upload_blog_image():
    """Завантажити зображення блогу у медіа-реєстр: HEIC/JPG/PNG/WebP -> WebP.

    Тепер усі зображення блогу йдуть через MediaFile (durable, з варіантами).
    Файл лишається без прив'язки (entity_id=None) до збереження допису, коли
    routes_blog прив'язує його за media_id. Повертає {url, thumb, card,
    media_id, width, height} -- блочний редактор і dropzone обкладинки.
    """
    from flask_login import current_user

    file = request.files.get('file')
    media, error = media_service.create_from_upload(
        file,
        entity_type=None,
        entity_id=None,
        usage_type='inline',
        uploader_id=current_user.id,
    )
    if error:
        return jsonify({'error': error}), 400
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to persist blog image upload')
        return jsonify({'error': 'Помилка збереження'}), 500

    audit_logger.info('Uploaded blog image (media %s): %s', media.id, media.file_path)
    return jsonify({
        'url': media.url,
        'thumb': media.variant_url('thumb'),
        'card': media.variant_url('card'),
        'media_id': media.id,
        'width': media.width,
        'height': media.height,
    }), 200


@admin_bp.route('/upload/trainer-certificate', methods=['POST'])
@admin_required
def upload_trainer_certificate():
    """Завантажити сертифікат тренера: HEIC/JPG/PNG/WebP -> WebP (full + thumb).

    Зберігається під trainers/{slug}/certificates/ (переживає деплої). Повертає
    {url, thumb, width, height} -- використовується редактором регалій.
    """
    file = request.files.get('file')
    slug = request.form.get('slug', '').strip()

    data, error = image_service.process_trainer_certificate(file, slug)
    if error:
        return jsonify({'error': error}), 400

    audit_logger.info('Uploaded trainer certificate: %s', data['url'])
    return jsonify(data), 200
