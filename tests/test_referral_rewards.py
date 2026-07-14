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
    # SiteSettings -- singleton, а award комітить -> скидаємо ВСІ реф-поля до
    # дефолтів, щоб налаштування не текли між тестами.
    s = SiteSettings.get()
    s.referral_enabled = True
    s.referral_points_per_paid = points
    s.referral_maturity_days = 0
    s.referral_max_per_referrer = 0
    s.referral_notify_referrer = True
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


def test_reaward_reactivates_voided(db_session):
    _enable(points=4)
    referrer = _mk_user('r8@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('b8@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode, ps='paid')

    rs.sync_reward_for_registration(reg)          # paid -> award
    assert rs.get_balance('user', referrer.id) == 4

    reg.payment_status = 'refunded'
    db.session.flush()
    rs.sync_reward_for_registration(reg)          # refunded -> void
    assert rs.get_balance('user', referrer.id) == 0

    reg.payment_status = 'paid'
    db.session.flush()
    rs.sync_reward_for_registration(reg)          # paid again -> reactivate
    assert rs.get_balance('user', referrer.id) == 4
    reward = ReferralReward.query.filter_by(registration_id=reg.id).first()
    assert reward.status == 'granted'
    assert reward.voided_at is None
    assert ReferralReward.query.filter_by(registration_id=reg.id).count() == 1


def test_sync_pending_leaves_reward_intact(db_session):
    _enable(points=6)
    referrer = _mk_user('r9@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('b9@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode, ps='paid')

    rs.sync_reward_for_registration(reg)          # paid -> award
    assert rs.get_balance('user', referrer.id) == 6

    reg.payment_status = 'pending'
    db.session.flush()
    rs.sync_reward_for_registration(reg)          # pending -> no-op
    assert rs.get_balance('user', referrer.id) == 6


def test_award_notifies_referrer_email(db_session, monkeypatch):
    _enable(points=5)
    referrer = _mk_user('notify-ref@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('notify-buy@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode)

    calls = []
    from app.services.email_service import EmailService
    monkeypatch.setattr(EmailService, 'send_referral_award',
                        staticmethod(lambda **kw: calls.append(kw)))

    rs.award_for_paid_registration(reg)
    assert len(calls) == 1
    assert calls[0]['to_email'] == 'notify-ref@example.com'
    assert calls[0]['points'] == 5
    assert calls[0]['balance'] == 5


def test_maturity_holds_then_matures(db_session):
    s = _enable(points=5)
    s.referral_maturity_days = 7
    db.session.flush()
    referrer = _mk_user('mat-ref@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('mat-buy@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode)

    reward = rs.award_for_paid_registration(reg)
    assert reward.status == 'pending'
    assert reward.matures_at is not None
    assert rs.get_balance('user', referrer.id) == 0       # ще не активні
    assert rs.get_pending_balance('user', referrer.id) == 5

    # Здвигаємо matures_at у минуле й запускаємо джобу дозрівання.
    from datetime import timedelta
    from app.models.mixins import utcnow
    reward.matures_at = utcnow() - timedelta(days=1)
    db.session.flush()
    assert rs.mature_referral_rewards() == 1
    assert rs.get_balance('user', referrer.id) == 5
    assert rs.get_pending_balance('user', referrer.id) == 0


def test_self_referral_by_email_blocked(db_session):
    _enable(points=5)
    # Тренер-реферер із тим самим email, що й покупець (різні таблиці, email
    # не гарантовано унікальний між User і Trainer) -> антифрод блокує.
    buyer = _mk_user('dup@example.com')
    trainer = Trainer(full_name='Дублер Тренер', slug='dubler-ref',
                      email='DUP@example.com')
    db.session.add(trainer)
    db.session.flush()
    tcode = rs.ensure_referral_code(trainer, prefix='t')
    reg = _mk_reg(buyer, _mk_course_instance(), code=tcode)

    assert rs.award_for_paid_registration(reg) is None
    assert rs.get_balance('trainer', trainer.id) == 0


def test_cap_limits_awards(db_session):
    s = _enable(points=5)
    s.referral_max_per_referrer = 1
    db.session.flush()
    referrer = _mk_user('cap-ref@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    ci = _mk_course_instance()

    b1 = _mk_user('cap-b1@example.com')
    r1 = _mk_reg(b1, ci, code=rcode)
    assert rs.award_for_paid_registration(r1) is not None

    b2 = _mk_user('cap-b2@example.com')
    r2 = _mk_reg(b2, _mk_course_instance(), code=rcode)
    assert rs.award_for_paid_registration(r2) is None      # стеля досягнута
    assert rs.get_balance('user', referrer.id) == 5


def test_manual_adjustment_affects_balance(db_session):
    _enable(points=5)
    referrer = _mk_user('adj-ref@example.com')
    rs.ensure_referral_code(referrer, prefix='u')

    rs.add_adjustment('user', referrer.id, 10, 'бонус вручну')
    assert rs.get_balance('user', referrer.id) == 10
    rs.add_adjustment('user', referrer.id, -3, 'корекція')
    assert rs.get_balance('user', referrer.id) == 7
    assert len(rs.list_adjustments('user', referrer.id)) == 2


def test_fraud_flags_high_void_and_no_conversion(db_session):
    _enable(points=5)
    # Реферер із багатьма поверненнями (voided >= active).
    ref1 = _mk_user('fraud1@example.com')
    c1 = rs.ensure_referral_code(ref1, prefix='u')
    for i in range(2):
        b = _mk_user(f'fb{i}@example.com')
        reg = _mk_reg(b, _mk_course_instance(), code=c1)
        rs.award_for_paid_registration(reg)
        reg.payment_status = 'refunded'
        db.session.flush()
        rs.void_for_registration(reg)

    # Реферер із трафіком без конверсій (кліки, 0 нарахувань).
    ref2 = _mk_user('fraud2@example.com')
    c2 = rs.ensure_referral_code(ref2, prefix='u')
    for _ in range(25):
        rs._increment_click(c2)
    db.session.commit()

    flags = rs.fraud_flags(min_clicks=20)
    ids = {f['id'] for f in flags}
    assert ref1.id in ids   # багато повернень
    assert ref2.id in ids   # трафік без конверсій


def test_reconcile_fixes_drift(db_session):
    _enable(points=5)
    referrer = _mk_user('recon@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('recon-b@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode)
    rs.award_for_paid_registration(reg)
    assert rs.get_balance('user', referrer.id) == 5

    # Симулюємо дрейф: псуємо денормалізовану колонку напряму.
    referrer.referral_balance = 999
    db.session.flush()
    denorm, real = rs.balances_drift()
    assert denorm != real

    fixed = rs.reconcile_balances()
    assert fixed >= 1
    assert rs.get_balance('user', referrer.id) == 5
    denorm2, real2 = rs.balances_drift()
    assert denorm2 == real2


def test_fraud_single_refund_not_flagged(db_session):
    _enable(points=5)
    # Один легітимний refund (voided=1, active=0) -- НЕ має позначатись.
    referrer = _mk_user('one-refund@example.com')
    rcode = rs.ensure_referral_code(referrer, prefix='u')
    buyer = _mk_user('one-refund-b@example.com')
    reg = _mk_reg(buyer, _mk_course_instance(), code=rcode)
    rs.award_for_paid_registration(reg)
    reg.payment_status = 'refunded'
    db.session.flush()
    rs.void_for_registration(reg)

    flags = rs.fraud_flags()
    assert referrer.id not in {f['id'] for f in flags}


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
