"""Tests for public partner API v1."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.event import Event
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User


API_KEY = 'test-partner-api-key-12345678901234567890'


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def partner_settings(app):
    s = SiteSettings.get()
    s.partner_integration_enabled = True
    s.partner_api_key = API_KEY
    s.partner_prefill_secret = 'test-prefill-secret-' + 'x' * 32
    db.session.commit()
    yield s
    s.partner_integration_enabled = False
    s.partner_api_key = ''
    s.partner_prefill_secret = ''
    db.session.commit()


@pytest.fixture
def user(app):
    u = User(email=f'api-{_uid()}@test.com', password='pw-' + _uid(), first_name='T', last_name='U')
    db.session.add(u)
    db.session.flush()
    return u


@pytest.fixture
def published_event(app, user):
    e = Event(
        title='Published Event', slug=f'pub-{_uid()}',
        short_description='desc', event_type='course', event_format='offline',
        status='published', price=1500,
        start_date=datetime.now(timezone.utc) + timedelta(days=10),
        end_date=datetime.now(timezone.utc) + timedelta(days=11),
        cpd_points=5, tags=['gynecology', 'ppp'],
        is_active=True, created_by=user.id,
    )
    db.session.add(e)
    db.session.flush()
    return e


@pytest.fixture
def draft_event(app, user):
    e = Event(
        title='Draft', slug=f'draft-{_uid()}',
        event_type='course', event_format='online', status='draft',
        price=0, is_active=True, created_by=user.id,
    )
    db.session.add(e)
    db.session.flush()
    return e


class TestEventsList:
    def test_requires_api_key(self, client, partner_settings, published_event):
        resp = client.get('/api/v1/events')
        assert resp.status_code == 401

    def test_rejects_wrong_api_key(self, client, partner_settings, published_event):
        resp = client.get('/api/v1/events', headers={'X-API-Key': 'wrong-key'})
        assert resp.status_code == 401

    def test_returns_404_when_integration_disabled(self, client, published_event):
        # partner_settings fixture not requested → integration stays disabled
        resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
        assert resp.status_code == 404

    def test_lists_published_events(self, client, partner_settings, published_event, draft_event):
        resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
        assert resp.status_code == 200
        data = resp.get_json()
        slugs = {e['slug'] for e in data['items']}
        assert published_event.slug in slugs
        assert draft_event.slug not in slugs

    def test_event_card_shape(self, client, partner_settings, published_event):
        resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
        card = next(e for e in resp.get_json()['items'] if e['slug'] == published_event.slug)
        assert card['title'] == 'Published Event'
        assert card['cpd_points'] == 5
        assert card['tags'] == ['gynecology', 'ppp']
        assert card['currency'] == 'UAH'
        assert card['registration_url'].endswith(f'/registration/{published_event.id}/register')
        assert card['detail_url'].endswith(f'/courses/{published_event.slug}')

    def test_pagination_bounds(self, client, partner_settings, published_event):
        resp = client.get(
            '/api/v1/events?per_page=9999',
            headers={'X-API-Key': API_KEY},
        )
        data = resp.get_json()
        assert data['per_page'] == 100  # capped


class TestEventDetail:
    def test_get_by_slug(self, client, partner_settings, published_event):
        resp = client.get(
            f'/api/v1/events/{published_event.slug}',
            headers={'X-API-Key': API_KEY},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['slug'] == published_event.slug
        assert 'program_blocks' in data
        assert 'description' in data

    def test_404_for_unknown_slug(self, client, partner_settings):
        resp = client.get(
            '/api/v1/events/nonexistent-slug-xyz',
            headers={'X-API-Key': API_KEY},
        )
        assert resp.status_code == 404

    def test_404_for_draft(self, client, partner_settings, draft_event):
        resp = client.get(
            f'/api/v1/events/{draft_event.slug}',
            headers={'X-API-Key': API_KEY},
        )
        assert resp.status_code == 404


class TestSeatsLeft:
    def test_null_when_unlimited_capacity(
        self, client, partner_settings, published_event,
    ):
        published_event.max_participants = None
        db.session.commit()
        resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
        card = next(
            e for e in resp.get_json()['items'] if e['slug'] == published_event.slug
        )
        assert card['seats_left'] is None

    def test_reflects_active_registrations(
        self, client, partner_settings, published_event, user,
    ):
        published_event.max_participants = 10
        db.session.add_all([
            EventRegistration(
                user_id=user.id, event_id=published_event.id,
                phone='+380000000001', specialty='s', workplace='w',
                status='confirmed', payment_status='paid',
            ),
        ])
        db.session.commit()
        resp = client.get('/api/v1/events', headers={'X-API-Key': API_KEY})
        card = next(
            e for e in resp.get_json()['items'] if e['slug'] == published_event.slug
        )
        assert card['seats_left'] == 9
