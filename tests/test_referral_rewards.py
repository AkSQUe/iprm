"""Тести Фази 3 реферальної програми: нарахування/анулювання/баланс.

Увага: award_for_paid_registration робить commit -> дані переживають
per-test rollback. Тому кожен тест використовує унікальні ключі (email,
slug) через лічильник, щоб не було колізій UNIQUE між тестами.
"""
import itertools
from decimal import Decimal

_seq = itertools.count(1)

from app.extensions import db
from app.models.user import User
from app.models.trainer import Trainer
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.referral_reward import ReferralReward
from app.models.site_settings import SiteSettings
from app.services import referral_service as rs


def _enable(points=5):
    s = SiteSettings.get()
    s.referral_enabled = True
    s.referral_points_per_paid = points
    db.session.flush()
    return s


def _mk_user(email):
    u = User(email=email, first_name='Т', last_name='Ю')
    db.session.add(u)
    db.session.flush()
    return u


def _mk_course_instance():
    n = next(_seq)
    c = Course(title='Курс', slug=f'kurs-ref-rewards-{n}', is_active=True)
    db.session.add(c)
    db.session.flush()
    ci = CourseInstance(course_id=c.id, status='published')
    db.session.add(ci)
    db.session.flush()
    return ci


def _mk_reg(user, instance, code=None, amount='1000', ps='paid'):
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id,
        phone='+380', specialty='x', workplace='y',
        payment_amount=Decimal(amount), payment_status=ps,
        status='confirmed', referral_code=code,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


def test_award_grants_points_to_user_referrer(db_session):
    _enable(points=7)
    referrer = _mk_user('referrer@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('buyer@example.com')
    ci = _mk_course_instance()
    reg = _mk_reg(buyer, ci, code=rcode)

    reward = rs.award_for_paid_registration(reg)
    assert reward is not None
    assert reward.points == 7
    assert reward.referrer_kind == 'user'
    assert reward.referrer_id == referrer.id
    assert rs.get_balance('user', referrer.id) == 7


def test_award_idempotent(db_session):
    _enable(points=5)
    referrer = _mk_user('r2@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('b2@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode)

    r1 = rs.award_for_paid_registration(reg)
    r2 = rs.award_for_paid_registration(reg)
    assert r1.id == r2.id
    assert ReferralReward.query.filter_by(registration_id=reg.id).count() == 1
    assert rs.get_balance('user', referrer.id) == 5


def test_no_award_for_free_registration(db_session):
    _enable(points=5)
    referrer = _mk_user('r3@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('b3@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode, amount='0')

    assert rs.award_for_paid_registration(reg) is None
    assert rs.get_balance('user', referrer.id) == 0


def test_no_award_when_disabled(db_session):
    s = SiteSettings.get()
    s.referral_enabled = False
    db.session.flush()
    referrer = _mk_user('r4@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('b4@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode)

    assert rs.award_for_paid_registration(reg) is None


def test_no_self_referral(db_session):
    _enable(points=5)
    buyer = _mk_user('self@example.com')
    rcode = rs.ensure_referral_code(buyer, prefix='u')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode)

    assert rs.award_for_paid_registration(reg) is None
    assert rs.get_balance('user', buyer.id) == 0


def test_void_removes_from_balance(db_session):
    _enable(points=5)
    referrer = _mk_user('r5@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('b5@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode)

    rs.award_for_paid_registration(reg)
    assert rs.get_balance('user', referrer.id) == 5

    rs.void_for_registration(reg)
    assert rs.get_balance('user', referrer.id) == 0
    reward = ReferralReward.query.filter_by(registration_id=reg.id).first()
    assert reward.status == 'voided'


def test_sync_awards_then_voids_on_refund(db_session):
    _enable(points=3)
    referrer = _mk_user('r6@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('b6@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode, ps='paid')

    rs.sync_reward_for_registration(reg)  # paid -> award
    assert rs.get_balance('user', referrer.id) == 3

    reg.payment_status = 'refunded'
    db.session.flush()
    rs.sync_reward_for_registration(reg)  # not paid -> void
    assert rs.get_balance('user', referrer.id) == 0


def test_trainer_referrer_balance(db_session):
    _enable(points=10)
    t = Trainer(full_name='Тренер Реф', slug='trener-ref-rw')
    db.session.add(t)
    db.session.flush()
    tcode = rs.ensure_referral_code(t, prefix='t')
    buyer = _mk_user('b7@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=tcode)

    reward = rs.award_for_paid_registration(reg)
    assert reward.referrer_kind == 'trainer'
    assert rs.get_balance('trainer', t.id) == 10
