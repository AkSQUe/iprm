"""Адмінські маршрути блогу: список, створення, редагування, видалення дописів.

Контент-блоки приходять як JSON у прихованому полі форми; перед збереженням
проганяються через blog_service.sanitize_content (whitelist тегів, локальні
URL зображень, валідний YouTube-id). Модерація коментарів -- у routes_blog_comments.
"""
import json
import logging

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy import func, desc
from sqlalchemy.exc import IntegrityError

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import BlogPostForm
from app.admin.routes_translations import apply_inline_translations
from app.extensions import db
from app.models.blog_post import BlogPost
from app.models.blog_comment import BlogComment
from app.models.media_file import MediaFile
from app.models.mixins import utcnow
from app.services import blog_service

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


_POST_STATES = {'published': 'Опубліковані', 'draft': 'Чернетки'}


@admin_bp.route('/blog')
@admin_required
def blog_list():
    from app.admin import _listing

    filters = {
        'q': _listing.text_arg('q'),
        'state': _listing.choice_arg('state', _POST_STATES),
    }
    query = _listing.apply_search(BlogPost.query, filters['q'], [
        BlogPost.title, BlogPost.slug, BlogPost.excerpt,
    ])
    if filters['state']:
        # Фільтруємо по колонці `status`, а не по property `is_published`:
        # у SQL її не існує.
        query = query.filter(BlogPost.status == filters['state'])
    posts = query.order_by(desc(BlogPost.created_at)).all()
    # Лічильники коментарів на модерації -- одним запитом (без N+1).
    pending = dict(
        db.session.query(BlogComment.post_id, func.count(BlogComment.id))
        .filter(BlogComment.status == BlogComment.STATUS_PENDING,
                BlogComment.deleted_at.is_(None))
        .group_by(BlogComment.post_id)
        .all()
    )
    total_pending = (
        db.session.query(func.count(BlogComment.id))
        .filter(BlogComment.status == BlogComment.STATUS_PENDING,
                BlogComment.deleted_at.is_(None))
        .scalar()
    )
    return render_template(
        'admin/blog_list.html',
        posts=posts, pending_counts=pending, total_pending=total_pending,
        filters=filters,
        state_options=list(_POST_STATES.items()),
    )


def _apply_form(post, form):
    """Перенести дані форми у допис (спільне для create/edit). Повертає помилку або None."""
    title = form.title.data.strip()
    slug = (form.slug.data or '').strip()
    if slug:
        slug = blog_service.slugify(slug)
        clash = BlogPost.query.filter(BlogPost.slug == slug, BlogPost.id != post.id).first()
        if clash:
            return 'Допис із таким slug уже існує'
    else:
        slug = blog_service.generate_unique_slug(title, exclude_id=post.id)

    # Контент: розпарсити JSON із редактора і санітизувати.
    try:
        raw_blocks = json.loads(form.content.data or '[]')
    except (ValueError, TypeError):
        raw_blocks = []
    blocks = blog_service.sanitize_content(raw_blocks)

    post.title = title
    post.slug = slug
    post.content = blocks
    # Обкладинка з реєстру: приймаємо media_id лише якщо такий MediaFile існує.
    cover_mid = (form.cover_media_id.data or '').strip()
    if cover_mid.isdigit() and db.session.get(MediaFile, int(cover_mid)):
        post.cover_media_id = int(cover_mid)
    else:
        post.cover_media_id = None
    post.excerpt = (form.excerpt.data or '').strip() or blog_service.auto_excerpt(blocks)
    post.meta_title = (form.meta_title.data or '').strip() or None
    post.meta_description = (form.meta_description.data or '').strip() or None

    new_status = form.status.data
    if new_status == BlogPost.STATUS_PUBLISHED and post.published_at is None:
        post.published_at = utcnow()
    post.status = new_status
    return None


def _remap_content(content, mapping):
    """Замінити url/thumb/card у image/gallery-блоках за mapping {old: new}."""
    out = []
    for blk in (content or []):
        if not isinstance(blk, dict):
            out.append(blk)
            continue
        blk = dict(blk)
        data = dict(blk.get('data') or {})
        if blk.get('type') == 'image':
            for k in ('url', 'thumb', 'card'):
                if data.get(k) in mapping:
                    data[k] = mapping[data[k]]
            blk['data'] = data
        elif blk.get('type') == 'gallery':
            imgs = []
            for img in (data.get('images') or []):
                if isinstance(img, dict):
                    img = dict(img)
                    for k in ('url', 'thumb', 'card'):
                        if img.get(k) in mapping:
                            img[k] = mapping[img[k]]
                imgs.append(img)
            data['images'] = imgs
            blk['data'] = data
        out.append(blk)
    return out


def _attach_media(post):
    """Прив'язати MediaFile (обкладинка + контент) до допису після збереження.

    Виставляє entity_type/entity_id/usage_type/sort_order, перейменовує файли у
    читабельну схему ({slug}-cover, {slug}-inline-N, {slug}-gallery-N) і оновлює
    URL у JSON-контенті. Відв'язані не видаляємо автоматично. Ідемпотентно."""
    from app.services import media_service

    assignments = {}  # media_id -> (usage_type, sort_order, index|None)
    if post.cover_media_id:
        assignments[post.cover_media_id] = ('cover', 0, None)
    sort = 1
    inline_i = gallery_i = 0
    for block in (post.content or []):
        if not isinstance(block, dict):
            continue
        data = block.get('data') or {}
        if block.get('type') == 'image':
            mid = data.get('media_id')
            if isinstance(mid, int) and mid not in assignments:
                inline_i += 1
                assignments[mid] = ('inline', sort, inline_i)
                sort += 1
        elif block.get('type') == 'gallery':
            for img in (data.get('images') or []):
                mid = (img or {}).get('media_id')
                if isinstance(mid, int) and mid not in assignments:
                    gallery_i += 1
                    assignments[mid] = ('gallery', sort, gallery_i)
                    sort += 1
    if not assignments:
        return
    rows = {m.id: m for m in MediaFile.query.filter(MediaFile.id.in_(list(assignments))).all()}
    mapping = {}
    for mid, (usage, sort_o, idx) in assignments.items():
        m = rows.get(mid)
        if not m:
            continue
        m.entity_type = 'blog_post'
        m.entity_id = post.id
        m.usage_type = usage
        m.sort_order = sort_o
        mapping.update(media_service.rename_for_entity(m, post.slug, idx))
    if mapping:
        post.content = _remap_content(post.content, mapping)
    try:
        db.session.commit()
    except Exception:
        logger.exception('Failed to attach media to blog post %s', post.id)
        db.session.rollback()


def _commit_post(post):
    """Закомітити допис із ретраєм на гонку за unique slug.

    Якщо два збереження одночасно взяли однаковий slug -- перший пройде,
    другий впаде IntegrityError; регенеруємо slug і пробуємо ще раз. Інші
    помилки прокидуються нагору (обробляються у viewʼю). Повертає True/False.
    """
    for _ in range(2):
        try:
            db.session.commit()
            return True
        except IntegrityError:
            db.session.rollback()
            post.slug = blog_service.generate_unique_slug(post.title, exclude_id=post.id)
            db.session.add(post)
    return False


@admin_bp.route('/blog/new', methods=['GET', 'POST'])
@admin_required
def blog_create():
    form = BlogPostForm()
    if request.method == 'GET':
        form.status.data = BlogPost.STATUS_DRAFT

    if form.validate_on_submit():
        post = BlogPost(author_id=current_user.id)
        error = _apply_form(post, form)
        if error:
            flash(error, 'error')
            return render_template('admin/blog_edit.html', form=form, post=None)
        db.session.add(post)
        apply_inline_translations(post)
        try:
            if _commit_post(post):
                _attach_media(post)
                audit_logger.info('Admin %s created blog post %s (%s)', current_user.email, post.id, post.slug)
                flash('Допис створено', 'success')
                return redirect(url_for('admin.blog_edit', post_id=post.id))
            flash('Не вдалося зберегти через колізію slug. Спробуйте інший slug.', 'error')
        except Exception:
            logger.exception('Failed to create blog post')
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/blog_edit.html', form=form, post=None)


@admin_bp.route('/blog/<int:post_id>/edit', methods=['GET', 'POST'])
@admin_required
def blog_edit(post_id):
    post = db.session.get(BlogPost, post_id)
    if not post:
        flash('Допис не знайдено', 'error')
        return redirect(url_for('admin.blog_list'))

    form = BlogPostForm(obj=post)
    if request.method == 'GET':
        # Прихований content -- серіалізуємо поточні блоки для редактора.
        form.content.data = json.dumps(post.content or [], ensure_ascii=False)

    if form.validate_on_submit():
        error = _apply_form(post, form)
        if error:
            flash(error, 'error')
            return render_template('admin/blog_edit.html', form=form, post=post)
        apply_inline_translations(post)
        try:
            if _commit_post(post):
                _attach_media(post)
                audit_logger.info('Admin %s updated blog post %s (%s)', current_user.email, post.id, post.slug)
                flash('Допис оновлено', 'success')
                return redirect(url_for('admin.blog_edit', post_id=post.id))
            flash('Не вдалося зберегти через колізію slug. Спробуйте інший slug.', 'error')
        except Exception:
            logger.exception('Failed to update blog post %d', post_id)
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/blog_edit.html', form=form, post=post)


@admin_bp.route('/blog/<int:post_id>/preview')
@admin_required
def blog_preview(post_id):
    """Прев'ю допису публічним шаблоном незалежно від статусу (admin-only).

    Дозволяє переглянути чернетку так, як вона виглядатиме на сайті, до
    публікації. Доступ обмежено admin_required (без публічного токена)."""
    post = db.session.get(BlogPost, post_id)
    if not post:
        flash('Допис не знайдено', 'error')
        return redirect(url_for('admin.blog_list'))
    from app.blog.routes import _approved_comment_tree
    children, roots, count = _approved_comment_tree(post.id)
    return render_template(
        'blog/post.html',
        active_nav='blog', post=post, preview=True,
        comment_children=children, comment_roots=roots, comment_count=count,
        max_comment_depth=BlogComment.MAX_DEPTH,
    )


@admin_bp.route('/blog/<int:post_id>/delete', methods=['POST'])
@admin_required
def blog_delete(post_id):
    post = db.session.get(BlogPost, post_id)
    if post:
        slug = post.slug
        db.session.delete(post)
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted blog post %s (%s)', current_user.email, post_id, slug)
            flash('Допис видалено', 'success')
        except Exception:
            logger.exception('Failed to delete blog post %d', post_id)
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.blog_list'))
