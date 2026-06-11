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


def _strip_media_from_blocks(content, media_id):
    """Прибрати з контенту блоку посилання на media_id (image/gallery)."""
    out = []
    for blk in (content or []):
        if not isinstance(blk, dict):
            out.append(blk)
            continue
        data = blk.get('data') or {}
        if blk.get('type') == 'image' and data.get('media_id') == media_id:
            continue  # цілий image-блок видаляємо
        if blk.get('type') == 'gallery':
            imgs = [i for i in (data.get('images') or [])
                    if not (isinstance(i, dict) and i.get('media_id') == media_id)]
            if not imgs:
                continue  # порожня галерея -> прибираємо блок
            blk = dict(blk)
            blk['data'] = {**data, 'images': imgs}
        out.append(blk)
    return out


def _detach_media_refs(media):
    """Прибрати посилання на media з JSON-полів сутності перед видаленням.

    FK-посилання (cover/photo/hero/card_media_id) обнуляються самою БД
    (ondelete=SET NULL). Тут чистимо лише JSON, де FK немає -- щоб не лишилось
    «битих» /media URL у контенті блогу та регаліях тренера."""
    et, eid, mid = media.entity_type, media.entity_id, media.id
    if not et or not eid:
        return
    if et == 'blog_post':
        from app.models.blog_post import BlogPost
        post = db.session.get(BlogPost, eid)
        if post and post.content:
            post.content = _strip_media_from_blocks(post.content, mid)
    elif et == 'trainer':
        from app.models.trainer import Trainer
        t = db.session.get(Trainer, eid)
        if not t:
            return
        if t.certificates:
            t.certificates = [c for c in t.certificates
                              if not (isinstance(c, dict) and c.get('media_id') == mid)]
        if t.patents:
            cleaned = []
            for p in t.patents:
                if isinstance(p, dict) and p.get('media_id') == mid:
                    p = {k: v for k, v in p.items() if k not in ('image', 'thumb', 'card', 'media_id')}
                    if not p.get('url'):
                        continue  # патент без скана й без посилання -> прибираємо
                cleaned.append(p)
            t.patents = cleaned


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


@admin_bp.route('/media/list.json')
@admin_required
def media_list_json():
    """JSON-список медіа для пікера в редакторах (вибір наявного файлу)."""
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

    pag = q.order_by(desc(MediaFile.created_at)).paginate(
        page=page, per_page=_PER_PAGE, error_out=False,
    )
    return jsonify({
        'items': [{
            'id': m.id, 'url': m.url,
            'thumb': m.variant_url('thumb'), 'card': m.variant_url('card'),
            'alt': m.alt_text or '', 'width': m.width, 'height': m.height,
        } for m in pag.items],
        'has_next': pag.has_next, 'page': pag.page,
    })


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
        was_attached = media.entity_type is not None
        _detach_media_refs(media)
        media_service.delete_media(media)
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted media %s', current_user.email, media_id)
            flash('Медіафайл видалено' + (' (відв\'язано від контенту)' if was_attached else ''), 'success')
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


@admin_bp.route('/media/bulk-delete', methods=['POST'])
@admin_required
def media_bulk_delete():
    """Видалити кілька медіа за раз (мультивибір у бібліотеці)."""
    ids = []
    for raw in request.form.getlist('ids'):
        if raw.isdigit():
            ids.append(int(raw))
    deleted = 0
    if ids:
        for media in MediaFile.query.filter(MediaFile.id.in_(ids)).all():
            _detach_media_refs(media)
            media_service.delete_media(media)
            deleted += 1
        try:
            db.session.commit()
            audit_logger.info('Admin %s bulk-deleted %d media', current_user.email, deleted)
            flash('Видалено медіафайлів: %d' % deleted, 'success')
        except Exception:
            db.session.rollback()
            logger.exception('Bulk media delete failed')
            flash('Помилка при видаленні', 'error')
    return redirect(url_for(
        'admin.media_library',
        entity_type=(request.form.get('entity_type') or None),
        usage_type=(request.form.get('usage_type') or None),
    ))
