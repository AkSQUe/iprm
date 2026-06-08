"""Публічний блог: список опублікованих дописів та сторінка допису.

Сабміт коментарів і їх показ -- у routes_comments (Фаза 5)."""
from datetime import datetime, timezone

from flask import render_template, abort, request

from app.blog import blog_bp
from app.extensions import db
from app.models.blog_post import BlogPost

_PER_PAGE = 9


def _published_query():
    now = datetime.now(timezone.utc)
    return (
        BlogPost.query
        .filter(BlogPost.status == BlogPost.STATUS_PUBLISHED)
        .filter(BlogPost.published_at.isnot(None))
        .filter(BlogPost.published_at <= now)
    )


@blog_bp.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    pagination = (
        _published_query()
        .order_by(BlogPost.published_at.desc())
        .paginate(page=page, per_page=_PER_PAGE, error_out=False)
    )
    return render_template(
        'blog/list.html',
        active_nav='blog',
        posts=pagination.items,
        pagination=pagination,
    )


@blog_bp.route('/<slug>')
def post_detail(slug):
    post = _published_query().filter(BlogPost.slug == slug).first()
    if not post:
        abort(404)

    # Best-effort лічильник переглядів (не критично -- не валимо запит на помилці).
    try:
        BlogPost.query.filter_by(id=post.id).update(
            {BlogPost.views: BlogPost.views + 1}, synchronize_session=False,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()

    return render_template(
        'blog/post.html',
        active_nav='blog',
        post=post,
    )
