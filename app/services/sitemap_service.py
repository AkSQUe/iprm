"""Sitemap generation service."""
from flask import current_app, url_for

from datetime import datetime, timezone

from app.i18n import localized_urls
from app.models.blog_post import BlogPost
from app.models.clinic import Clinic
from app.models.course import Course
from app.models.trainer import Trainer


def _expand_localized(endpoint, priority, freq, lastmod=None, **kwargs):
    """Записи sitemap для ендпоінта: локалізовані -- по одному URL на мову
    з xhtml:link-альтернативами (hreflang, включно з x-default=uk);
    нелокалізовані (юридичні тощо) -- один запис без альтернатив."""
    if not current_app.url_map.is_endpoint_expecting(endpoint, 'lang_code'):
        return [{
            'loc': url_for(endpoint, _external=True, **kwargs),
            'priority': priority, 'changefreq': freq, 'lastmod': lastmod,
        }]
    alternates = localized_urls(endpoint, kwargs, external=True, x_default=True)
    # Перші len(LANGUAGES) записів -- по одному URL на мову (без x-default).
    return [{
        'loc': alt['url'],
        'priority': priority, 'changefreq': freq, 'lastmod': lastmod,
        'alternates': alternates,
    } for alt in alternates if alt['lang'] != 'x-default']


STATIC_URLS = [
    ('main.index', '1.0', 'daily'),
    ('courses.course_list', '0.9', 'weekly'),
    ('online.course_list', '0.8', 'weekly'),
    ('main.labs', '0.8', 'weekly'),
    ('trainers.trainer_list', '0.8', 'weekly'),
    ('blog.index', '0.7', 'weekly'),
    ('clinics.clinic_list', '0.8', 'monthly'),
    ('main.contact', '0.7', 'monthly'),
    ('main.sitemap_page', '0.3', 'monthly'),
    ('main.bpr_documents', '0.4', 'yearly'),
    ('main.offer', '0.3', 'yearly'),
    ('main.privacy', '0.3', 'yearly'),
    ('main.refund', '0.3', 'yearly'),
    ('main.disclaimer', '0.3', 'yearly'),
    ('main.cookies', '0.3', 'yearly'),
]


def generate_pages():
    """Build the list of sitemap page dicts."""
    pages = []

    for endpoint, priority, freq in STATIC_URLS:
        pages.extend(_expand_localized(endpoint, priority, freq))

    courses = Course.query.filter_by(is_active=True).all()
    for course in courses:
        pages.extend(_expand_localized(
            'courses.course_by_slug', '0.8', 'weekly',
            lastmod=course.updated_at.strftime('%Y-%m-%d') if course.updated_at else None,
            slug=course.slug,
        ))

    from app.models.online_course import OnlineCourse
    online_courses = OnlineCourse.query.filter_by(
        is_published=True, is_vanished=False,
    ).all()
    for online_course in online_courses:
        pages.extend(_expand_localized(
            'online.course_detail', '0.7', 'weekly',
            lastmod=online_course.updated_at.strftime('%Y-%m-%d')
            if online_course.updated_at else None,
            slug=online_course.slug,
        ))

    trainers = Trainer.query.filter_by(is_active=True).all()
    for trainer in trainers:
        pages.extend(_expand_localized(
            'trainers.trainer_detail', '0.6', 'monthly',
            lastmod=trainer.updated_at.strftime('%Y-%m-%d') if trainer.updated_at else None,
            slug=trainer.slug,
        ))

    clinics = Clinic.query.filter_by(is_active=True).all()
    for clinic in clinics:
        pages.extend(_expand_localized(
            'clinics.clinic_detail', '0.6', 'monthly',
            lastmod=clinic.updated_at.strftime('%Y-%m-%d') if clinic.updated_at else None,
            slug=clinic.slug,
        ))

    now = datetime.now(timezone.utc)
    posts = (
        BlogPost.query
        .filter(BlogPost.status == BlogPost.STATUS_PUBLISHED)
        .filter(BlogPost.published_at.isnot(None), BlogPost.published_at <= now)
        .all()
    )
    for post in posts:
        pages.extend(_expand_localized(
            'blog.post_detail', '0.7', 'monthly',
            lastmod=post.updated_at.strftime('%Y-%m-%d') if post.updated_at else None,
            slug=post.slug,
        ))

    return pages


def generate_visual_sitemap():
    """Build structured data for the visual HTML sitemap page."""
    sections = []

    sections.append({
        'title': 'Курси',
        'icon': 'courses',
        'links': [
            {'label': 'Каталог курсів', 'url': url_for('courses.course_list')},
        ],
    })

    courses = Course.query.filter_by(is_active=True).order_by(Course.title).all()
    if courses:
        sections[-1]['children'] = [
            {'label': c.t('title'), 'url': url_for('courses.course_by_slug', slug=c.slug)}
            for c in courses
        ]

    sections.append({
        'title': 'Тренери',
        'icon': 'trainers',
        'links': [
            {'label': 'Список тренерів', 'url': url_for('trainers.trainer_list')},
        ],
    })
    trainers = Trainer.query.filter_by(is_active=True).order_by(Trainer.full_name).all()
    if trainers:
        sections[-1]['children'] = [
            {'label': t.t('full_name'), 'url': url_for('trainers.trainer_detail', slug=t.slug)}
            for t in trainers
        ]

    sections.append({
        'title': 'Блог',
        'icon': 'blog',
        'links': [
            {'label': 'Усі статті', 'url': url_for('blog.index')},
        ],
    })
    now = datetime.now(timezone.utc)
    posts = (
        BlogPost.query
        .filter(BlogPost.status == BlogPost.STATUS_PUBLISHED)
        .filter(BlogPost.published_at.isnot(None), BlogPost.published_at <= now)
        .order_by(BlogPost.published_at.desc())
        .limit(20)
        .all()
    )
    if posts:
        sections[-1]['children'] = [
            {'label': p.t('title'), 'url': url_for('blog.post_detail', slug=p.slug)}
            for p in posts
        ]

    sections.append({
        'title': 'Клініки',
        'icon': 'clinics',
        'links': [
            {'label': 'Каталог клінік', 'url': url_for('clinics.clinic_list')},
        ],
    })
    clinics = Clinic.query.filter_by(is_active=True).order_by(Clinic.name).all()
    if clinics:
        sections[-1]['children'] = [
            {'label': cl.t('name'), 'url': url_for('clinics.clinic_detail', slug=cl.slug)}
            for cl in clinics
        ]

    sections.append({
        'title': 'Навчання',
        'icon': 'education',
        'links': [
            {'label': 'Лабораторії', 'url': url_for('main.labs')},
            {'label': 'Документи БПР', 'url': url_for('main.bpr_documents')},
        ],
    })

    sections.append({
        'title': 'Контакти',
        'icon': 'contacts',
        'links': [
            {'label': 'Зворотний зв\'язок', 'url': url_for('main.contact')},
        ],
    })

    sections.append({
        'title': 'Інформація',
        'icon': 'info',
        'links': [
            {'label': 'Оферта', 'url': url_for('main.offer')},
            {'label': 'Конфіденційність', 'url': url_for('main.privacy')},
            {'label': 'Повернення коштів', 'url': url_for('main.refund')},
            {'label': 'Дисклеймер', 'url': url_for('main.disclaimer')},
            {'label': 'Cookie', 'url': url_for('main.cookies')},
        ],
    })

    return sections
