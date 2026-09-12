"""Адмінська медіа-бібліотека: перегляд, фільтри, alt, видалення, кошик.

Завантаження -- через спільний /admin/upload/media (routes_uploads). Тут --
керування реєстром MediaFile: список з фільтрами/сортуванням/пагінацією,
редагування alt-тексту, видалення й повернення. Прив'язка до сутностей
робиться в редакторах блогу/тренерів/курсів (фази 3-5).

Видалення м'яке: рядок лишається з позначкою deleted_at, файли на диску --
теж, тож дію можна відкотити. Остаточно видаляє і рядок, і файли фонова
задача purge_soft_deleted (app.services.scheduler_service) через
RETENTION_DAYS. Доти видалене видно у зрізі `state=trash` -- інакше вікно
відкату існувало б лише поки на екрані висить тост «Повернути».
"""
import logging

from flask import render_template, request, jsonify, flash, url_for
from flask_login import current_user
from sqlalchemy import and_, case, desc, func
from sqlalchemy.orm import selectinload

from app.admin import _listing, admin_bp
from app.admin._helpers import try_commit
from app.rbac import permission_required
from app.extensions import db
from app.models.media_file import MediaFile
from app.undo import offer_undo

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

_PER_PAGE = 24

# Стеля на кількість id в одній масовій дії. Без неї POST зі ста тисячами
# значень давав би IN-клаузу на сто тисяч параметрів -- той самий клас
# запобіжника, що `_listing.MAX_PAGE` для номера сторінки.
_MAX_BULK_IDS = 200

_ENTITY_CHOICES = ('none',) + tuple(MediaFile.ENTITY_LABELS)
_STATES = {'trash': 'У кошику'}
_SORT_LABELS = {'size': 'Спершу важкі', 'oldest': 'Спершу старі'}

_SEARCH_COLUMNS = (
    MediaFile.file_path, MediaFile.original_name, MediaFile.alt_text,
)


def _media_filters():
    """Зріз бібліотеки -- спільний для сторінки й для `_back()`.

    Кожне значення звірене: `choice_arg` мовчки скидає невідоме в типове,
    тож ?usage_type=<сміття> зі старого посилання дає повний список, а не
    порожній екран.
    """
    return {
        'q': _listing.text_arg('q'),
        'entity_type': _listing.choice_arg('entity_type', _ENTITY_CHOICES),
        'usage_type': _listing.choice_arg('usage_type', MediaFile.USAGE_TYPES),
        'state': _listing.choice_arg('state', _STATES),
        'sort': _listing.sort_arg(_SORT_LABELS),
    }


def _back():
    """Безпечний POST -> GET редірект назад на той самий зріз (НЕ referrer:
    той керований клієнтом і відкриває open redirect). Джерело значень --
    query-string самого запиту дії: форми несуть зріз у своєму action-URL
    через `back_args`, і читається він тими самими `choice_arg`/`text_arg`,
    що й у роуті списку."""
    return _listing.back_redirect('admin.media_library', _media_filters())


def _ids_arg(raw_values):
    """Список id для масової дії, зі стелею `_MAX_BULK_IDS`."""
    out = []
    for raw in raw_values:
        if raw and raw.strip().isdigit():
            out.append(int(raw))
        if len(out) >= _MAX_BULK_IDS:
            break
    return out


def _library_stats():
    """Зведення по ВСІЙ бібліотеці одним запитом.

    Свідомо не залежить від активного фільтра: це підсумок сховища, а
    скільки знайдено в поточному зрізі -- каже пагінатор. Доти те саме
    коштувало два повні COUNT на кожен рендер, і обидва мовчки ігнорували
    фільтр, через що під зрізом «Блог» у шапці стояли цифри всієї
    бібліотеки без жодної позначки про це.

    `case`, а не `count(...).filter(...)`: FILTER-клауза є не в кожній
    складанці SQLite, на якій ганяються тести.
    """
    alive = MediaFile.deleted_at.is_(None)
    total, unattached, size, trashed = db.session.query(
        func.sum(case((alive, 1), else_=0)),
        func.sum(case((and_(alive, MediaFile.entity_type.is_(None)), 1), else_=0)),
        func.sum(case((alive, MediaFile.file_size), else_=0)),
        func.sum(case((MediaFile.deleted_at.isnot(None), 1), else_=0)),
    ).one()
    return {
        'total': int(total or 0),
        'unattached': int(unattached or 0),
        'bytes': int(size or 0),
        'trashed': int(trashed or 0),
    }


def _apply_owner_filters(query, entity_type, usage_type):
    """Спільне для сторінки й для JSON-пікера звуження за власником."""
    if entity_type == 'none':
        query = query.filter(MediaFile.entity_type.is_(None))
    elif entity_type:
        query = query.filter(MediaFile.entity_type == entity_type)
    if usage_type:
        query = query.filter(MediaFile.usage_type == usage_type)
    return query


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


def _prefetch_owners(medias):
    """Підняти власників ОДНИМ запитом на тип перед циклом видалення.

    `_detach_media_refs` бере власника через `db.session.get`, і після цього
    префетчу він дістається з identity map безкоштовно. Доти масове
    видалення 24 файлів із різних дописів коштувало до 24 окремих SELECT.
    """
    from app.models.blog_post import BlogPost
    from app.models.trainer import Trainer

    models = {'blog_post': BlogPost, 'trainer': Trainer}
    buckets = {}
    for media in medias:
        if media.entity_type in models and media.entity_id:
            buckets.setdefault(media.entity_type, set()).add(media.entity_id)
    for entity_type, ids in buckets.items():
        model = models[entity_type]
        model.query.filter(model.id.in_(ids)).all()


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
@permission_required('media.view')
def media_library():
    filters = _media_filters()
    trash = filters['state'] == 'trash'

    # Кошик -- дзеркальний зріз: рівно ті рядки, які `alive()` відсікає.
    query = (MediaFile.query.filter(MediaFile.deleted_at.isnot(None))
             if trash else MediaFile.alive())
    query = _apply_owner_filters(query, filters['entity_type'], filters['usage_type'])
    # Пошук за іменем файлу й alt-текстом: у бібліотеці на сотні мініатюр
    # прокрутка -- єдиний спосіб знайти потрібне зображення.
    query = _listing.apply_search(query, filters['q'], list(_SEARCH_COLUMNS))
    # Картка друкує, хто завантажив: без eager це рядок на файл.
    query = query.options(selectinload(MediaFile.uploader))

    # id у порядку -- не косметика: без нього рядки з однаковою міткою часу
    # (пакетне завантаження) можуть переставлятись між сторінками, і один
    # файл видно двічі, а інший не видно взагалі.
    if filters['sort'] == 'size':
        order = (desc(MediaFile.file_size), desc(MediaFile.id))
    elif filters['sort'] == 'oldest':
        order = (MediaFile.created_at.asc(), MediaFile.id.asc())
    else:
        order = (desc(MediaFile.created_at), desc(MediaFile.id))

    pagination = query.order_by(*order).paginate(
        page=_listing.page_arg(), per_page=_PER_PAGE, error_out=False,
    )
    active = _listing.filter_args(filters)
    return render_template(
        'admin/media_library.html',
        items=pagination.items, pagination=pagination,
        filters=filters, trash=trash,
        filter_args=active,
        back_args=_listing.back_args(active, pagination.page),
        entity_options=([('none', "Без прив'язки")]
                        + list(MediaFile.ENTITY_LABELS.items())),
        usage_options=list(MediaFile.USAGE_LABELS.items()),
        state_options=list(_STATES.items()),
        sort_options=list(_SORT_LABELS.items()),
        entity_labels=MediaFile.ENTITY_LABELS,
        usage_labels=MediaFile.USAGE_LABELS,
        stats=_library_stats(),
    )


@admin_bp.route('/media/list.json')
@permission_required('media.view')
def media_list_json():
    """JSON-список медіа для пікера в редакторах (вибір наявного файлу)."""
    entity_type = _listing.choice_arg('entity_type', _ENTITY_CHOICES)
    usage_type = _listing.choice_arg('usage_type', MediaFile.USAGE_TYPES)
    search = _listing.text_arg('q')
    page = _listing.page_arg()

    query = _apply_owner_filters(MediaFile.alive(), entity_type, usage_type)
    # Той самий пошук, що й на сторінці: доти потрібне зображення в редакторі
    # шукали прокруткою по 24, хоча бібліотека поруч уміла шукати.
    query = _listing.apply_search(query, search, list(_SEARCH_COLUMNS))

    # limit+1 замість paginate(): відповідь віддає лише `has_next`, а
    # paginate рахував би ще й COUNT, якого ніхто не читає.
    rows = (query.order_by(desc(MediaFile.created_at), desc(MediaFile.id))
            .offset((page - 1) * _PER_PAGE).limit(_PER_PAGE + 1).all())
    has_next = len(rows) > _PER_PAGE
    return jsonify({
        'items': [{
            'id': m.id, 'url': m.url,
            'thumb': m.variant_url('thumb'), 'card': m.variant_url('card'),
            'alt': m.alt_text or '', 'width': m.width, 'height': m.height,
        } for m in rows[:_PER_PAGE]],
        'has_next': has_next, 'page': page,
    })


@admin_bp.route('/media/<int:media_id>/alt', methods=['POST'])
@permission_required('media.manage')
def media_update_alt(media_id):
    media = db.session.get(MediaFile, media_id)
    if not media:
        return jsonify({'error': 'not found'}), 404
    media.alt_text = (request.form.get('alt') or '').strip()[:255] or None
    # Не `try_commit`: він flash-ить, а відповідь тут читає fetch -- flash
    # виринув би на НАСТУПНІЙ сторінці, поза зв'язком із дією.
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to update media alt %s', media_id)
        return jsonify({'error': 'save failed'}), 500
    return jsonify({'ok': True, 'alt': media.alt_text or ''}), 200


@admin_bp.route('/media/<int:media_id>/delete', methods=['POST'])
@permission_required('media.delete')
def media_delete(media_id):
    """М'яке видалення: файл лишається на диску до purge, тож відкат можливий.

    Undo пропонуємо ЛИШЕ для непривʼязаних файлів. Для привʼязаного видалення
    додатково вичищає посилання на нього з контенту (блоки блогу, регалії
    тренера), а їх restore не поверне -- обіцяти повний відкат там не можна.
    """
    media = db.session.get(MediaFile, media_id)
    if media and not media.is_deleted:
        was_attached = media.entity_type is not None
        if was_attached:
            _detach_media_refs(media)
        media.soft_delete()
        # Побічні ефекти -- після коміту й ПОЗА його try. Доти виняток у
        # url_for/offer_undo відкочував уже закомічену транзакцію і писав
        # «Помилка при видаленні» над файлом, якого вже не було.
        if try_commit(f'media delete {media_id}', 'Помилка при видаленні'):
            audit_logger.info('Admin %s deleted media %s', current_user.email, media_id)
            if was_attached:
                flash("Медіафайл видалено (відв'язано від контенту)", 'success')
            else:
                offer_undo(
                    'Медіафайл видалено',
                    url_for('admin.media_restore', ids=str(media_id)),
                )
    return _back()


@admin_bp.route('/media/bulk-delete', methods=['POST'])
@permission_required('media.delete')
def media_bulk_delete():
    """Видалити кілька медіа за раз (мультивибір у бібліотеці)."""
    ids = _ids_arg(request.form.getlist('ids'))
    deleted, detached = [], 0
    if ids:
        rows = MediaFile.alive().filter(MediaFile.id.in_(ids)).all()
        _prefetch_owners(rows)
        for media in rows:
            if media.entity_type is not None:
                _detach_media_refs(media)
                detached += 1
            media.soft_delete()
            deleted.append(media.id)
        if try_commit('media bulk delete', 'Помилка при видаленні'):
            audit_logger.info(
                'Admin %s bulk-deleted %d media', current_user.email, len(deleted),
            )
            # Відкат пропонуємо, лише якщо жодного посилання в контенті не
            # чіпали -- інакше повернувся б файл, але не місце, де він стояв.
            if deleted and not detached:
                offer_undo(
                    'Видалено медіафайлів: %d' % len(deleted),
                    url_for('admin.media_restore',
                            ids=','.join(str(i) for i in deleted)),
                )
            elif deleted:
                flash('Видалено медіафайлів: %d' % len(deleted), 'success')
    return _back()


@admin_bp.route('/media/restore', methods=['POST'])
@permission_required('media.manage')
def media_restore():
    """Відкат м'якого видалення.

    Два джерела id, бо два виклики: тост «Повернути» несе їх у query-string
    через кому (посилання будується в момент видалення), кошик -- полями
    форми. Ламати перший не можна: він живе у вже відданій користувачу
    сторінці.
    """
    raw = request.form.getlist('ids') or (request.args.get('ids') or '').split(',')
    ids = _ids_arg(raw)
    restored = 0
    if ids:
        rows = MediaFile.query.filter(
            MediaFile.id.in_(ids), MediaFile.deleted_at.isnot(None),
        ).all()
        for media in rows:
            media.restore()
            restored += 1
        if not try_commit('media restore', 'Помилка при відновленні'):
            return _back()
        audit_logger.info(
            'Admin %s restored %d media', current_user.email, restored,
        )
    if restored:
        flash('Повернено медіафайлів: %d' % restored, 'success')
    else:
        flash('Файли вже не можна повернути', 'error')
    return _back()
