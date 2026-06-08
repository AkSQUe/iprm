"""Публічний блог: список опублікованих дописів та сторінка допису.

Сабміт коментарів і їх показ -- у routes_comments (Фаза 5)."""
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import format_datetime

from flask import render_template, abort, request, url_for, Response

from app.blog import blog_bp
from app.models.blog_post import BlogPost
from app.models.blog_comment import BlogComment

_PER_PAGE = 9
_FEED_LIMIT = 20


def _approved_comment_tree(post_id):
    """Схвалені коментарі допису -> (children_map, roots, count).

    children_map[parent_id] = [коментарі...]; roots = children_map[None].
    Один запит, дерево будуємо в памʼяті (без N+1).
    """
    rows = (
        BlogComment.query
        .filter_by(post_id=post_id, status=BlogComment.STATUS_APPROVED)
        .order_by(BlogComment.created_at.asc())
        .all()
    )
    approved_ids = {c.id for c in rows}
    children = defaultdict(list)
    roots = []
    for c in rows:
        # Коментар -- корінь, якщо без батька АБО його батько не серед схвалених
        # (напр. батько ще на модерації/спам) -- щоб схвалена відповідь не зникала.
        if c.parent_id is None or c.parent_id not in approved_ids:
            roots.append(c)
        else:
            children[c.parent_id].append(c)
    return children, roots, len(rows)


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


@blog_bp.route('/feed.xml')
def feed():
    """RSS 2.0 стрічка останніх опублікованих дописів."""
    posts = (
        _published_query()
        .order_by(BlogPost.published_at.desc())
        .limit(_FEED_LIMIT)
        .all()
    )
    items = [
        {
            'title': p.title,
            'link': url_for('blog.post_detail', slug=p.slug, _external=True),
            'description': p.excerpt or p.title,
            'pub_date': format_datetime(p.published_at) if p.published_at else '',
        }
        for p in posts
    ]
    last_build = format_datetime(posts[0].published_at) if posts and posts[0].published_at else ''
    xml = render_template(
        'blog/feed.xml',
        items=items,
        feed_link=url_for('blog.index', _external=True),
        last_build=last_build,
    )
    return Response(xml, mimetype='application/rss+xml')


@blog_bp.route('/<slug>')
def post_detail(slug):
    post = _published_query().filter(BlogPost.slug == slug).first()
    if not post:
        abort(404)

    children, roots, comment_count = _approved_comment_tree(post.id)
    return render_template(
        'blog/post.html',
        active_nav='blog',
        post=post,
        comment_children=children,
        comment_roots=roots,
        comment_count=comment_count,
        max_comment_depth=BlogComment.MAX_DEPTH,
    )
