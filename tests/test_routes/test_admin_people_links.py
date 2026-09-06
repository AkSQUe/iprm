"""Люди в реєстрах адмінки ведуть у картку контакту (`user_detail`).

Замовлення онлайн-курсів, заявки на повернення, історія промокоду й
нарахування реферальної програми показують ПІБ покупця/учасника окремим
текстом -- жодна з цих сторінок досі нікуди не вела. Кожен тест перевіряє
САМЕ тег навколо імені: інакше перевірка пройшла б і на нерозгорнутому
тексті.
"""
from tests.support.rbac import grant_role
import re
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.promo_code import PromoCode, PromoRedemption
from app.models.refund_request import RefundRequest
from app.models.referral_reward import ReferralReward
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import promo_service


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'pl-{_uid()}@test.com', 'password123',
        first_name='P', last_name='L', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_online_order_buyer_links_to_user_detail(client, admin):
    buyer = User.create_with_password(
        f'pl-{_uid()}@test.com', 'password123',
        first_name='Оксана', last_name='Гриценко', email_confirmed=True,
    )
    db.session.flush()
    course = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name=f'Онлайн {_uid()}', slug=f'pl-{_uid()}',
        price=Decimal('1000'),
    )
    db.session.add(course)
    db.session.flush()
    order = OnlineEnrollment(
        user_id=buyer.id, online_course_id=course.id,
        payment_amount=Decimal('1000'), payment_status='paid', status='active',
    )
    db.session.add(order)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/online-orders?q={buyer.email}').get_data(as_text=True)
        href = f'/admin/users/{buyer.id}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*{re.escape(buyer.full_name)}', html)
    finally:
        db.session.delete(db.session.merge(order))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(buyer))
        db.session.commit()


def test_refund_request_participant_links_to_user_detail(client, admin):
    user = User.create_with_password(
        f'pl-{_uid()}@test.com', 'password123',
        first_name='Марія', last_name='Ткаченко', email_confirmed=True,
    )
    db.session.flush()
    course = Course(title=f'Курс {_uid()}', slug=f'pl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380671110004',
        specialty='T', workplace='Клініка', status='confirmed', payment_status='paid',
        payment_amount=Decimal('1000'),
    )
    db.session.add(reg)
    db.session.flush()
    reason = f'pl-{_uid()} причина'
    refund = RefundRequest(
        registration_id=reg.id, user_id=user.id, reason=reason,
        quoted_percent=100, quoted_amount=Decimal('1000'), quoted_code='C1',
    )
    db.session.add(refund)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/refund-requests?q={reason}').get_data(as_text=True)
        href = f'/admin/users/{user.id}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*{re.escape(user.full_name)}', html)
    finally:
        db.session.delete(db.session.merge(refund))
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(user))
        db.session.commit()


def test_promo_redemption_participant_links_to_user_detail(client, admin):
    user = User.create_with_password(
        f'pl-{_uid()}@test.com', 'password123',
        first_name='Ганна', last_name='Іванова', email_confirmed=True,
    )
    db.session.flush()
    course = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name=f'Онлайн {_uid()}', slug=f'pl-{_uid()}',
        price=Decimal('2000'),
    )
    db.session.add(course)
    db.session.flush()
    enrollment = OnlineEnrollment(
        user_id=user.id, online_course_id=course.id,
        payment_amount=Decimal('1000'), payment_status='paid', status='active',
    )
    db.session.add(enrollment)
    db.session.flush()
    code = f'PL-{_uid()}'
    promo = PromoCode(code=code, code_norm=promo_service.normalize_code(code),
                      discount_type='percent', discount_value=Decimal('50'))
    db.session.add(promo)
    db.session.flush()
    redemption = PromoRedemption(
        promo_code_id=promo.id, enrollment_id=enrollment.id, user_id=user.id,
        original_amount=Decimal('2000'), discount_amount=Decimal('1000'),
        final_amount=Decimal('1000'), status='applied',
    )
    db.session.add(redemption)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/promo-codes/{promo.id}').get_data(as_text=True)
        href = f'/admin/users/{user.id}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*{re.escape(user.full_name)}', html)
    finally:
        db.session.delete(db.session.merge(redemption))
        db.session.delete(db.session.merge(promo))
        db.session.delete(db.session.merge(enrollment))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(user))
        db.session.commit()


def _reward_setup(prefix):
    """Реєстрація + нарахування для перевірки таблиці «Нарахування».

    Спільне для referrals.html і referral_detail.html: обидва читають
    ту саму пару (учасник, захід) з `reg`/`reg.instance`.
    """
    user = User.create_with_password(
        f'{prefix}-{_uid()}@test.com', 'password123',
        first_name='Ірина', last_name='Бондар', email_confirmed=True,
    )
    db.session.flush()
    course = Course(title=f'Курс {_uid()}', slug=f'{prefix}-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline')
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380671110005',
        specialty='T', workplace='Клініка', status='confirmed', payment_status='paid',
        payment_amount=Decimal('1000'), referral_code=f'u{_uid()}',
    )
    db.session.add(reg)
    db.session.flush()
    reward = ReferralReward(
        registration_id=reg.id, referrer_kind='user', referrer_id=user.id,
        referral_code=reg.referral_code, points=100, status='granted',
    )
    db.session.add(reward)
    db.session.commit()
    return user, course, inst, reg, reward


def _teardown_reward(user, course, inst, reg, reward):
    db.session.delete(db.session.merge(reward))
    db.session.delete(db.session.merge(reg))
    db.session.delete(db.session.merge(inst))
    db.session.delete(db.session.merge(course))
    db.session.delete(db.session.merge(user))
    db.session.commit()


def test_referrals_overview_reward_links_participant_and_course(client, admin):
    user, course, inst, reg, reward = _reward_setup('pl')
    _login(client, admin)
    try:
        html = client.get(f'/admin/referrals?q={user.email}').get_data(as_text=True)
        user_href = f'/admin/users/{user.id}'
        course_href = f'/admin/instances/{inst.id}/registrations'
        assert re.search(
            rf'<a href="{re.escape(user_href)}">\s*{re.escape(reg.user.first_name)}\s*{re.escape(reg.user.last_name)}',
            html,
        )
        assert re.search(rf'<a href="{re.escape(course_href)}">\s*{re.escape(course.title)}', html)
    finally:
        _teardown_reward(user, course, inst, reg, reward)


def test_referrer_detail_reward_links_participant_and_course(client, admin):
    user, course, inst, reg, reward = _reward_setup('pl')
    _login(client, admin)
    try:
        html = client.get(f'/admin/referrals/user/{user.id}').get_data(as_text=True)
        user_href = f'/admin/users/{user.id}'
        course_href = f'/admin/instances/{inst.id}/registrations'
        assert re.search(
            rf'<a href="{re.escape(user_href)}">\s*{re.escape(reg.user.first_name)}\s*{re.escape(reg.user.last_name)}',
            html,
        )
        assert re.search(rf'<a href="{re.escape(course_href)}">\s*{re.escape(course.title)}', html)
    finally:
        _teardown_reward(user, course, inst, reg, reward)
