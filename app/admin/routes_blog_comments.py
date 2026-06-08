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

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


@admin_bp.route('/blog/comments')
@admin_required
def blog_comments():
    status = request.args.get('status', BlogComment.STATUS_PENDING)
    if status not in BlogComment.STATUSES and status != 'all':
        status = BlogComment.STATUS_PENDING
    q = BlogComment.query
    if status != 'all':
        q = q.filter(BlogComment.status == status)
    comments = q.order_by(desc(BlogComment.created_at)).limit(200).all()
    return render_template('admin/blog_comments.html', comments=comments, status=status)


def _set_status(comment_id, new_status):
    comment = db.session.get(BlogComment, comment_id)
    if not comment:
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
    return redirect(request.referrer or url_for('admin.blog_comments'))


@admin_bp.route('/blog/comments/<int:comment_id>/spam', methods=['POST'])
@admin_required
def blog_comment_spam(comment_id):
    _set_status(comment_id, BlogComment.STATUS_SPAM)
    return redirect(request.referrer or url_for('admin.blog_comments'))


@admin_bp.route('/blog/comments/<int:comment_id>/delete', methods=['POST'])
@admin_required
def blog_comment_delete(comment_id):
    comment = db.session.get(BlogComment, comment_id)
    if comment:
        db.session.delete(comment)
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted comment %s', current_user.email, comment_id)
            flash('Коментар видалено', 'success')
        except Exception:
            logger.exception('Failed to delete comment %d', comment_id)
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(request.referrer or url_for('admin.blog_comments'))
