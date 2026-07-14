"""Тест публічного кабінету реферера за токеном (тренери без логіну)."""
from uuid import uuid4

from app.extensions import db
from app.models.trainer import Trainer
from app.models.site_settings import SiteSettings
from app.services import referral_service as rs


def test_dashboard_renders_for_valid_token(client, db_session):
    s = SiteSettings.get()
    s.referral_enabled = True
    s.website_url = 'https://plasma-regen.com'
    db.session.flush()
    t = Trainer(full_name='Кабінет Тренер', slug=f'kab-{uuid4().hex[:6]}')
    db.session.add(t)
    db.session.flush()
    rs.ensure_referral_code(t, prefix='t')

    token = rs.make_referrer_token('trainer', t.id)
    r = client.get(f'/r/{token}')
    assert r.status_code == 200
    assert 'Кабінет Тренер'.encode() in r.data
    assert b'ref=' in r.data  # посилання присутнє


def test_dashboard_404_on_bad_token(client, db_session):
    s = SiteSettings.get()
    s.referral_enabled = True
    db.session.flush()
    assert client.get('/r/not-a-real-token').status_code == 404


def test_dashboard_404_when_disabled(client, db_session):
    s = SiteSettings.get()
    s.referral_enabled = False
    db.session.flush()
    token = rs.make_referrer_token('trainer', 1)
    assert client.get(f'/r/{token}').status_code == 404
