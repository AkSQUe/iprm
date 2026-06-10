"""Адмінська медіа-бібліотека: перегляд, фільтри, alt, видалення.

Завантаження -- через спільний /admin/upload/media (routes_uploads). Тут --
керування реєстром MediaFile: список з фільтрами/пагінацією, редагування
alt-тексту, видалення (з файлами). Прив'язка до сутностей робиться в
редакторах блогу/тренерів/курсів (фази 3-5)."""
import logging

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user
from sqlalchemy import desc

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.media_file import MediaFile
from app.services import media_service

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

_PER_PAGE = 24


@admin_bp.route('/media')
@admin_required
def media_library():
    entity_type = (request.args.get('entity_type') or '').strip()
    usage_type = (request.args.get('usage_type') or '').strip()
    page = request.args.get('page', 1, type=int)

    q = MediaFile.query
    if entity_type == 'none':
        q = q.filter(MediaFile.entity_type.is_(None))
    elif entity_type:
        q = q.filter(MediaFile.entity_type == entity_type)
    if usage_type:
        q = q.filter(MediaFile.usage_type == usage_type)

    pagination = q.order_by(desc(MediaFile.created_at)).paginate(
        page=page, per_page=_PER_PAGE, error_out=False,
    )
    stats = {
        'total': MediaFile.query.count(),
        'unattached': MediaFile.query.filter(MediaFile.entity_type.is_(None)).count(),
    }
    return render_template(
        'admin/media_library.html',
        items=pagination.items, pagination=pagination,
        entity_type=entity_type, usage_type=usage_type,
        usage_types=MediaFile.USAGE_TYPES, stats=stats,
    )


@admin_bp.route('/media/<int:media_id>/alt', methods=['POST'])
@admin_required
def media_update_alt(media_id):
    media = db.session.get(MediaFile, media_id)
    if not media:
        return jsonify({'error': 'not found'}), 404
    media.alt_text = (request.form.get('alt') or '').strip()[:255] or None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to update media alt %s', media_id)
        return jsonify({'error': 'save failed'}), 500
    return jsonify({'ok': True, 'alt': media.alt_text or ''}), 200


@admin_bp.route('/media/<int:media_id>/delete', methods=['POST'])
@admin_required
def media_delete(media_id):
    media = db.session.get(MediaFile, media_id)
    if media:
        media_service.delete_media(media)
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted media %s', current_user.email, media_id)
            flash('Медіафайл видалено', 'success')
        except Exception:
            db.session.rollback()
            logger.exception('Failed to delete media %s', media_id)
            flash('Помилка при видаленні', 'error')
    # Без request.referrer (open redirect): повертаємось у бібліотеку зі
    # збереженням фільтра через приховані поля форми.
    return redirect(url_for(
        'admin.media_library',
        entity_type=(request.form.get('entity_type') or None),
        usage_type=(request.form.get('usage_type') or None),
        page=(request.form.get('page') or None),
    ))
