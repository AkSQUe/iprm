"""Тести реферальної програми (Фаза 1): генерація кодів і побудова посилань."""
from app.extensions import db
from app.models.user import User
from app.models.trainer import Trainer
from app.models.site_settings import SiteSettings
from app.services import referral_service as rs


def _mk_user(email):
    u = User(email=email, first_name='Тест', last_name='Юзер')
    db.session.add(u)
    db.session.flush()
    return u


def test_ensure_code_generates_prefixed_unique(db_session):
    u = _mk_user('ref1@example.com')
    code = u.get_referral_code()
    assert code.startswith('u')
    assert len(code) == 9  # 'u' + 8 hex
    # Ідемпотентність: повторний виклик повертає той самий код.
    assert u.get_referral_code() == code


def test_user_and_trainer_codes_distinct_prefixes(db_session):
    u = _mk_user('ref2@example.com')
    t = Trainer(full_name='Іван Тренер', slug='ivan-trener-ref')
    db.session.add(t)
    db.session.flush()

    ucode = rs.ensure_referral_code(u, prefix='u')
    tcode = rs.ensure_referral_code(t, prefix='t')
    assert ucode.startswith('u')
    assert tcode.startswith('t')
    assert ucode != tcode


def test_build_referral_url_appends_ref_and_utm(db_session):
    settings = SiteSettings.get()
    settings.website_url = 'https://plasma-regen.com'
    db.session.flush()

    url = rs.build_referral_url('uabcd1234', target_url='/courses/prp', medium='participant')
    assert 'https://plasma-regen.com/courses/prp' in url
    assert 'ref=uabcd1234' in url
    assert 'utm_source=referral' in url
    assert 'utm_medium=participant' in url
    assert 'utm_campaign=referral' in url


def test_build_referral_url_preserves_existing_query(db_session):
    settings = SiteSettings.get()
    settings.website_url = 'https://plasma-regen.com'
    db.session.flush()

    url = rs.build_referral_url('u1', target_url='/x?a=1', medium='trainer')
    assert 'a=1' in url
    assert 'ref=u1' in url


def test_user_referral_link_uses_participant_medium(db_session):
    settings = SiteSettings.get()
    settings.website_url = 'https://plasma-regen.com'
    u = _mk_user('ref3@example.com')
    db.session.flush()

    link = rs.user_referral_link(u, target_url='/courses/prp')
    assert 'utm_medium=participant' in link
    assert ('ref=' + u.referral_code) in link
