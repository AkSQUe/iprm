"""Адмінська модерація коментарів блогу.

Премодерація: нові коментарі мають статус 'pending' і не показуються публічно,
доки адмін не схвалить ('approved') чи не позначить спамом ('spam').
"""
import logging

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from sqlalchemy import desc

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.blog_comment import BlogComment
from app.models.mixins import utcnow
from app.undo import offer_undo

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


def _back():
    """Безпечний редірект назад до списку зі збереженням фільтра статусу.

    НЕ використовуємо request.referrer (керований клієнтом -> open redirect):
    будуємо URL через url_for з валідованим status із форми.
    """
    status = request.form.get('status')
    if status not in BlogComment.STATUSES and status != 'all':
        status = None
    return redirect(url_for('admin.blog_comments', status=status) if status
                    else url_for('admin.blog_comments'))


@admin_bp.route('/blog/comments')
@admin_required
def blog_comments():
    status = request.args.get('status', BlogComment.STATUS_PENDING)
    if status not in BlogComment.STATUSES and status != 'all':
        status = BlogComment.STATUS_PENDING
    q = BlogComment.alive()
    if status != 'all':
        q = q.filter(BlogComment.status == status)
    comments = q.order_by(desc(BlogComment.created_at)).limit(200).all()
    return render_template('admin/blog_comments.html', comments=comments, status=status)


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
