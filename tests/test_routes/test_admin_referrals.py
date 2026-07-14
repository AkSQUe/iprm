"""Тести адмін-сторінки реферальної програми (рендер + дані)."""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.user import User
from app.models.trainer import Trainer
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.services import referral_service as rs


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'a-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_referrals_page_renders_empty(client, admin):
    _login(client, admin)
    r = client.get('/admin/referrals')
    assert r.status_code == 200
    assert 'Реферальна програма'.encode() in r.data


def test_referrals_page_shows_reward(client, admin):
    s = SiteSettings.get()
    s.referral_enabled = True
    s.referral_points_per_paid = 5
    db.session.flush()

    referrer = User(email=f'ref-{uuid4().hex[:6]}@t.com', first_name='Реф', last_name='Ер')
    db.session.add(referrer)
    db.session.flush()
    code = rs.ensure_referral_code(referrer, prefix='u')

    buyer = User(email=f'buy-{uuid4().hex[:6]}@t.com', first_name='По', last_name='Ку')
    db.session.add(buyer)
    db.session.flush()

    c = Course(title='Курс Адмін', slug=f'kurs-adm-{uuid4().hex[:6]}', is_active=True)
    db.session.add(c)
    db.session.flush()
    ci = CourseInstance(course_id=c.id, status='published')
    db.session.add(ci)
    db.session.flush()
    reg = EventRegistration(
        user_id=buyer.id, instance_id=ci.id, phone='+380', specialty='x',
        workplace='y', payment_amount=Decimal('1000'), payment_status='paid',
        status='confirmed', referral_code=code,
    )
    db.session.add(reg)
    db.session.flush()
    rs.award_for_paid_registration(reg)

    _login(client, admin)
    r = client.get('/admin/referrals')
    assert r.status_code == 200
    # Ім'я реферера (у канонічному порядку "Прізвище Ім'я") присутнє.
    assert referrer.full_name.encode() in r.data
