"""Tests for dynamic sitemap.xml and robots.txt routes."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.clinic import Clinic
from app.models.course import Course
from app.models.trainer import Trainer


@pytest.fixture
def sample_data(app):
    """Створює по одному активному та одному неактивному об'єкту кожного типу."""
    active_course = Course(title='Active', slug=f'sm-c-{uuid4().hex[:6]}', is_active=True)
    inactive_course = Course(title='Inactive', slug=f'sm-c-inactive-{uuid4().hex[:6]}', is_active=False)
    active_trainer = Trainer(full_name='Active', slug=f'sm-t-{uuid4().hex[:6]}', is_active=True)
    inactive_trainer = Trainer(full_name='Inactive', slug=f'sm-t-inactive-{uuid4().hex[:6]}', is_active=False)
    active_clinic = Clinic(name='Active', slug=f'sm-cl-{uuid4().hex[:6]}', is_active=True)
    inactive_clinic = Clinic(name='Inactive', slug=f'sm-cl-inactive-{uuid4().hex[:6]}', is_active=False)
    db.session.add_all([
        active_course, inactive_course,
        active_trainer, inactive_trainer,
        active_clinic, inactive_clinic,
    ])
    db.session.flush()
    return {
        'active_course': active_course,
        'inactive_course': inactive_course,
        'active_trainer': active_trainer,
        'inactive_trainer': inactive_trainer,
        'active_clinic': active_clinic,
        'inactive_clinic': inactive_clinic,
    }


class TestSitemapXml:
    def test_returns_xml_content_type(self, client):
        resp = client.get('/sitemap.xml')
        assert resp.status_code == 200
        assert 'application/xml' in resp.content_type

    def test_has_cache_header(self, client):
        resp = client.get('/sitemap.xml')
        assert 'public' in resp.headers.get('Cache-Control', '')
        assert 'max-age=3600' in resp.headers.get('Cache-Control', '')

    def test_contains_static_urls(self, client):
        resp = client.get('/sitemap.xml')
        body = resp.data.decode('utf-8')
        assert '<urlset' in body
        assert '/courses/' in body  # courses_list endpoint
        assert '/contact' in body
        assert '/privacy' in body

    def test_includes_active_entities(self, client, sample_data):
        resp = client.get('/sitemap.xml')
        body = resp.data.decode('utf-8')
        assert sample_data['active_course'].slug in body
        assert sample_data['active_trainer'].slug in body
        assert sample_data['active_clinic'].slug in body

    def test_excludes_inactive_entities(self, client, sample_data):
        resp = client.get('/sitemap.xml')
        body = resp.data.decode('utf-8')
        assert sample_data['inactive_course'].slug not in body
        assert sample_data['inactive_trainer'].slug not in body
        assert sample_data['inactive_clinic'].slug not in body

    def test_has_lastmod_for_courses(self, client, sample_data):
        """lastmod з updated_at має бути у форматі YYYY-MM-DD."""
        resp = client.get('/sitemap.xml')
        body = resp.data.decode('utf-8')
        import re
        # Sitemap Spec допускає YYYY-MM-DD або W3C datetime.
        assert re.search(r'<lastmod>\d{4}-\d{2}-\d{2}</lastmod>', body)


class TestRobotsTxt:
    def test_returns_plain_text(self, client):
        resp = client.get('/robots.txt')
        assert resp.status_code == 200
        assert 'text/plain' in resp.content_type

    def test_references_sitemap(self, client):
        resp = client.get('/robots.txt')
        assert b'Sitemap:' in resp.data
        assert b'/sitemap.xml' in resp.data

    def test_disallows_private_paths(self, client):
        resp = client.get('/robots.txt')
        body = resp.data.decode('utf-8')
        assert 'Disallow: /admin/' in body
        assert 'Disallow: /registration/' in body
        assert 'Disallow: /auth/' in body
