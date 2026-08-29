"""Адмінська модерація коментарів блогу.

Премодерація: нові коментарі мають статус 'pending' і не показуються публічно,
доки адмін не схвалить ('approved') чи не позначить спамом ('spam').
"""
import logging

from flask import render_template, url_for, flash, request, abort
from flask_login import current_user
from sqlalchemy import desc

from app.admin import _listing, admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.blog_comment import BlogComment
from app.models.blog_post import BlogPost
from app.models.mixins import utcnow
from app.undo import offer_undo

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

# status -- окремий параметр (стрічка admin-pills, не поле filter_bar), тож
# 'all' звірений тут поруч, а не в STATUSES моделі.
_STATUS_CHOICES = BlogComment.STATUSES + ('all',)


def _filters():
    """Фільтри реєстру -- спільні для списку й для `_back()`."""
    return {
        'q': _listing.text_arg('q'),
        'post_id': _listing.int_arg('post_id'),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _status_arg():
    """Зріз статусу: звірка з переліком, невідоме значення падає в 'pending'."""
    return _listing.choice_arg('status', _STATUS_CHOICES, default=BlogComment.STATUS_PENDING)


def _post_options():
    """Дописи з хоча б одним живим коментарем -- інакше селект стає
    переліком усього блогу, а не тим, чим можна реально звузити список."""
    rows = (
        db.session.query(BlogPost.id, BlogPost.title)
        .join(BlogComment, BlogComment.post_id == BlogPost.id)
        .filter(BlogComment.deleted_at.is_(None))
        .distinct()
        .order_by(BlogPost.title)
        .all()
    )
    return [(post_id, title) for post_id, title in rows]


def _back():
    """Безпечний редірект назад до списку зі збереженням поточного зрізу.

    Спільний `_listing.back_redirect` перечитує й перевіряє кожен параметр
    зрізу тим самим способом, що й роут списку (НЕ request.referrer -- той
    керований клієнтом і відкриває open redirect). Джерело значень -- query
    string самого запиту дії (approve/spam/delete): рядкові форми несуть
    зріз у action-URL через `back_args`, прихованих полів тут більше немає.
    """
    return _listing.back_redirect(
        'admin.blog_comments', _filters(), {'status': _status_arg()},
    )


@admin_bp.route('/blog/comments')
@admin_required
def blog_comments():
    status = _status_arg()
    filters = _filters()
    query = BlogComment.alive()
    if status != 'all':
        query = query.filter(BlogComment.status == status)
    query = _listing.apply_search(query, filters['q'], [
        BlogComment.author_name, BlogComment.email, BlogComment.body,
    ])
    if filters['post_id']:
        query = query.filter(BlogComment.post_id == filters['post_id'])
    query = _listing.apply_date_range(
        query, BlogComment.created_at, filters['date_from'], filters['date_to'],
    )
    pagination = query.order_by(desc(BlogComment.created_at)).paginate(
        page=request.args.get('page', 1, type=int),
        per_page=_listing.per_page_arg(), error_out=False,
    )
    filter_args = _listing.filter_args(filters)
    return render_template(
        'admin/blog_comments.html',
        comments=pagination.items,
        pagination=pagination,
        status=status,
        filters=filters,
        filter_args=filter_args,
        back_args=_listing.back_args(filter_args, pagination.page, {'status': status}),
        post_options=_post_options(),
        per_page_options=_listing.PER_PAGE_OPTIONS,
    )


def _set_status(comment_id, new_status):
    comment = db.session.get(BlogComment, comment_id)
    if not comment or comment.is_deleted:
        abort(404)
    comment.status = new_status
    try:
        db.session.commit()
        audit_logger.info('Admin %s set comment %s -> %s', current_user.email, comment_id, new_status)
    except Exception:
        logger.exception('Failed to set comment %d status', comment_id)
        db.session.rollback()
        flash('Помилка при збереженні', 'error')
        return
    flash('Коментар оновлено', 'success')


@admin_bp.route('/blog/comments/<int:comment_id>/approve', methods=['POST'])
@admin_required
def blog_comment_approve(comment_id):
    _set_status(comment_id, BlogComment.STATUS_APPROVED)
    return _back()


@admin_bp.route('/blog/comments/<int:comment_id>/spam', methods=['POST'])
@admin_required
def blog_comment_spam(comment_id):
    _set_status(comment_id, BlogComment.STATUS_SPAM)
    return _back()


def _subtree(comment):
    """Коментар разом із відповідями на нього (глибина обмежена MAX_DEPTH).

    Гілку ховаємо цілком: інакше відповіді лишились би висіти без батька.
    Раніше те саме робив каскад delete-orphan при жорсткому видаленні.
    """
    out, queue = [], [comment]
    while queue:
        node = queue.pop()
        out.append(node)
        queue.extend(r for r in node.replies if not r.is_deleted)
    return out


@admin_bp.route('/blog/comments/<int:comment_id>/delete', methods=['POST'])
@admin_required
def blog_comment_delete(comment_id):
    """М'яке видалення гілки: діалогу немає, натомість тост із відкатом."""
    comment = db.session.get(BlogComment, comment_id)
    if comment and not comment.is_deleted:
        batch = _subtree(comment)
        # Спільна позначка часу -- за нею відкат поверне рівно цю гілку.
        stamp = utcnow()
        for node in batch:
            node.deleted_at = stamp
        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s deleted comment %s (+%d replies)',
                current_user.email, comment_id, len(batch) - 1,
            )
            extra = '' if len(batch) == 1 else ' і відповідей: %d' % (len(batch) - 1)
            offer_undo(
                'Коментар видалено%s' % extra,
                url_for('admin.blog_comment_restore', comment_id=comment_id),
            )
        except Exception:
            logger.exception('Failed to delete comment %d', comment_id)
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return _back()


@admin_bp.route('/blog/comments/<int:comment_id>/restore', methods=['POST'])
@admin_required
def blog_comment_restore(comment_id):
    comment = db.session.get(BlogComment, comment_id)
    if not comment or not comment.is_deleted:
        flash('Коментар уже не можна повернути', 'error')
        return _back()
    stamp = comment.deleted_at
    # Повертаємо рівно ту гілку, що зникла разом із ним (спільний deleted_at),
    # не зачіпаючи відповідей, видалених окремо раніше.
    restored = 0
    for node in BlogComment.query.filter(BlogComment.deleted_at == stamp).all():
        node.restore()
        restored += 1
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s restored comment %s (%d rows)',
            current_user.email, comment_id, restored,
        )
        flash('Коментар повернено', 'success')
    except Exception:
        logger.exception('Failed to restore comment %d', comment_id)
        db.session.rollback()
        flash('Помилка при відновленні', 'error')
    return _back()
