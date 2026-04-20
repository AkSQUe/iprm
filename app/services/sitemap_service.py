"""Sitemap generation service."""
from flask import url_for

from app.models.clinic import Clinic
from app.models.course import Course
from app.models.trainer import Trainer


STATIC_URLS = [
    ('courses.course_list', '1.0', 'weekly'),
    ('main.labs', '0.8', 'weekly'),
    ('trainers.trainer_list', '0.8', 'weekly'),
    ('clinics.clinic_list', '0.8', 'monthly'),
    ('main.contact', '0.7', 'monthly'),
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
        pages.append({
            'loc': url_for(endpoint, _external=True),
            'priority': priority,
            'changefreq': freq,
        })

    courses = Course.query.filter_by(is_active=True).all()
    for course in courses:
        pages.append({
            'loc': url_for('courses.course_by_slug', slug=course.slug, _external=True),
            'priority': '0.8',
            'changefreq': 'weekly',
            'lastmod': course.updated_at.strftime('%Y-%m-%d') if course.updated_at else None,
        })

    trainers = Trainer.query.filter_by(is_active=True).all()
    for trainer in trainers:
        pages.append({
            'loc': url_for('trainers.trainer_detail', slug=trainer.slug, _external=True),
            'priority': '0.6',
            'changefreq': 'monthly',
            'lastmod': trainer.updated_at.strftime('%Y-%m-%d') if trainer.updated_at else None,
        })

    clinics = Clinic.query.filter_by(is_active=True).all()
    for clinic in clinics:
        pages.append({
            'loc': url_for('clinics.clinic_detail', slug=clinic.slug, _external=True),
            'priority': '0.6',
            'changefreq': 'monthly',
            'lastmod': clinic.updated_at.strftime('%Y-%m-%d') if clinic.updated_at else None,
        })

    return pages
