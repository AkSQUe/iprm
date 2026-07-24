"""Публічний сабміт коментарів блогу.

Анти-спам: honeypot (website) + reCAPTCHA v3 + rate-limit. Усі коментарі
створюються у статусі 'pending' (премодерація). Підтримка відповідей:
parent_id з обмеженням глибини (BlogComment.MAX_DEPTH)."""
import logging

from email_validator import EmailNotValidError, validate_email
from flask import abort, current_app, flash, redirect, request, url_for
from flask_babel import gettext as _

from app.blog import blog_bp
from app.extensions import db, limiter
from app.models.blog_post import BlogPost
from app.models.blog_comment import BlogComment
from app.services import blog_service
from app.services.recaptcha import verify_request as verify_recaptcha

logger = logging.getLogger(__name__)

_EMAIL_MAX = 254


def _published_post(slug):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return (
        BlogPost.query
        .filter(BlogPost.slug == slug, BlogPost.status == BlogPost.STATUS_PUBLISHED)
        .filter(BlogPost.published_at.isnot(None), BlogPost.published_at <= now)
        .first()
    )


# Запобіжник від нескінченного циклу при пошкоджених даних (parent_id-цикл).
_MAX_HOPS = BlogComment.MAX_DEPTH + 5


def _comment_depth(comment):
    """Глибина коментаря: корінь = 1 (рахуємо предків угору, з лімітом hops)."""
    depth = 1
    node = comment
    hops = 0
    while node.parent_id is not None and hops < _MAX_HOPS:
        node = db.session.get(BlogComment, node.parent_id)
        if node is None:
            break
        depth += 1
        hops += 1
    return depth


def _resolve_parent(post_id, raw_parent_id):
    """Валідний предок (схвалений, того ж допису) із клампом глибини.

    Якщо нова відповідь перевищила б MAX_DEPTH -- піднімаємо батька вгору,
    щоб ланцюг лишився в межах. Повертає parent_id або None.
    """
    if not raw_parent_id:
        return None
    try:
        pid = int(raw_parent_id)
    except (ValueError, TypeError):
        return None
    parent = db.session.get(BlogComment, pid)
    if (parent is None or parent.post_id != post_id
            or parent.status != BlogComment.STATUS_APPROVED):
        return None
    # дитина матиме глибину parent_depth + 1; тримаємо <= MAX_DEPTH
    hops = 0
    while parent is not None and hops < _MAX_HOPS and _comment_depth(parent) + 1 > BlogComment.MAX_DEPTH:
        parent = db.session.get(BlogComment, parent.parent_id) if parent.parent_id else None
        hops += 1
    return parent.id if parent else None


@blog_bp.route('/<slug>/comment', methods=['POST'])
@limiter.limit('5 per hour; 20 per day', methods=['POST'])
def submit_comment(slug):
    post = _published_post(slug)
    if not post:
        abort(404)

    redirect_url = url_for('blog.post_detail', slug=slug)

    # Honeypot: приховане поле website -> мовчазний "успіх" (не сигналимо боту).
    if (request.form.get('website') or '').strip():
        current_app.logger.info('blog comment honeypot triggered slug=%s', slug)
        return redirect(redirect_url + '#comments')

    if not verify_recaptcha(action='blog_comment'):
        flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
        return redirect(redirect_url + '#comment-form')

    name = blog_service.clean_comment_name(request.form.get('name'))
    body = blog_service.clean_comment_body(request.form.get('body'))
    email_raw = (request.form.get('email') or '').strip()

    if not name:
        flash(_('Вкажіть імʼя'), 'error')
        return redirect(redirect_url + '#comment-form')
    if not body:
        flash(_('Напишіть текст коментаря'), 'error')
        return redirect(redirect_url + '#comment-form')

    email = None
    if email_raw:
        if len(email_raw) > _EMAIL_MAX:
            flash(_('Email задовгий'), 'error')
            return redirect(redirect_url + '#comment-form')
        try:
            email = validate_email(email_raw, check_deliverability=False).normalized
        except EmailNotValidError:
            flash(_('Вкажіть валідний email'), 'error')
            return redirect(redirect_url + '#comment-form')

    parent_id = _resolve_parent(post.id, request.form.get('parent_id'))

    comment = BlogComment(
        post_id=post.id,
        parent_id=parent_id,
        author_name=name,
        email=email,
        body=body,
        status=BlogComment.STATUS_PENDING,
        ip=(request.remote_addr or '')[:45],
    )
    db.session.add(comment)
    try:
        db.session.commit()
        flash(_('Дякуємо! Коментар надіслано на модерацію.'), 'success')
        # Best-effort нотифікація адміна; збій пошти не впливає на UX.
        try:
            from app.services.email_service import EmailService
            EmailService.send_blog_comment_notification(comment)
        except Exception:
            current_app.logger.exception('Failed to send blog comment notification')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to save blog comment for post_id=%s', post.id)
        flash(_('Помилка при надсиланні. Спробуйте ще раз.'), 'error')

    return redirect(redirect_url + '#comments')
