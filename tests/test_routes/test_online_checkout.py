"""Чекаут онлайн-курсу і перехід за тимчасовим посиланням."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.mixins import utcnow
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.user import User

ACCESS_URL = 'https://multimededu.sintegrum.com/register/secret-abc'


@pytest.fixture(autouse=True)
def clean(app):
    OnlineEnrollment.query.delete()
    OnlineCourse.query.delete()
    db.session.commit()
    yield
    OnlineEnrollment.query.delete()
    OnlineCourse.query.delete()
    db.session.commit()


@pytest.fixture
def buyer(app):
    user = User.create_with_password(
        f'buy-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Ольга', last_name='Коваль', email_confirmed=True,
    )
    db.session.commit()
    return user


@pytest.fixture
def course(app):
    item = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Плазмотерапія',
        slug=f'ck-{uuid4().hex[:8]}',
        price=Decimal('4500'),
        access_url=ACCESS_URL,
        is_published=True,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


# ----------------------------- гейт логіну -----------------------------

def test_checkout_requires_login(client, course):
    response = client.get(f'/online-courses/{course.slug}/checkout')
    assert response.status_code in (302, 401)


def test_checkout_creates_order(client, buyer, course):
    _login(client, buyer)
    response = client.get(f'/online-courses/{course.slug}/checkout')

    assert response.status_code == 200
    enrollment = OnlineEnrollment.query.filter_by(
        user_id=buyer.id, online_course_id=course.id,
    ).one()
    assert enrollment.payment_amount == Decimal('4500')
    assert enrollment.payment_status == 'unpaid'


def test_repeat_checkout_does_not_duplicate_order(client, buyer, course):
    _login(client, buyer)
    client.get(f'/online-courses/{course.slug}/checkout')
    client.get(f'/online-courses/{course.slug}/checkout')

    assert OnlineEnrollment.query.filter_by(user_id=buyer.id).count() == 1


def test_price_is_frozen_at_order_time(client, buyer, course):
    _login(client, buyer)
    client.get(f'/online-courses/{course.slug}/checkout')

    course.price = Decimal('9999')
    db.session.commit()

    enrollment = OnlineEnrollment.query.filter_by(user_id=buyer.id).one()
    assert enrollment.payment_amount == Decimal('4500')


def test_checkout_of_unpublished_course_is_404(client, buyer, course):
    course.is_published = False
    db.session.commit()
    _login(client, buyer)

    assert client.get(
        f'/online-courses/{course.slug}/checkout'
    ).status_code == 404


def test_paid_course_redirects_to_account(client, buyer, course):
    enrollment = OnlineEnrollment(
        user_id=buyer.id, online_course_id=course.id,
        payment_amount=Decimal('4500'), payment_status='paid', status='active',
    )
    db.session.add(enrollment)
    db.session.commit()
    _login(client, buyer)

    response = client.get(f'/online-courses/{course.slug}/checkout')
    assert response.status_code == 302
    assert '/account' in response.headers['Location']


def test_access_url_not_in_checkout_html(client, buyer, course):
    _login(client, buyer)
    body = client.get(
        f'/online-courses/{course.slug}/checkout'
    ).get_data(as_text=True)
    assert 'secret-abc' not in body


# ----------------------------- тимчасове посилання -----------------------------

def _paid_enrollment(buyer, course, ttl_hours=72):
    enrollment = OnlineEnrollment(
        user_id=buyer.id, online_course_id=course.id,
        payment_amount=Decimal('4500'), payment_status='paid', status='active',
        paid_at=utcnow(),
    )
    db.session.add(enrollment)
    db.session.flush()
    enrollment.issue_access_token(ttl_hours)
    enrollment.provisioned_at = utcnow()
    db.session.commit()
    return enrollment


def test_valid_token_redirects_to_sintegrum(client, buyer, course):
    enrollment = _paid_enrollment(buyer, course)

    response = client.get(f'/online-courses/access/{enrollment.access_token}')
    assert response.status_code == 302
    assert response.headers['Location'] == ACCESS_URL


def test_expired_token_does_not_redirect(client, buyer, course):
    enrollment = _paid_enrollment(buyer, course)
    enrollment.access_expires_at = utcnow() - timedelta(hours=1)
    db.session.commit()

    response = client.get(f'/online-courses/access/{enrollment.access_token}')
    assert response.status_code == 410
    body = response.get_data(as_text=True)
    assert ACCESS_URL not in body
    assert 'secret-abc' not in body


def test_unknown_token_is_404(client):
    response = client.get('/online-courses/access/no-such-token')
    assert response.status_code == 404


def test_refunded_order_token_stops_working(client, buyer, course):
    enrollment = _paid_enrollment(buyer, course)
    token = enrollment.access_token
    enrollment.payment_status = 'refunded'
    db.session.commit()

    response = client.get(f'/online-courses/access/{token}')
    assert response.status_code == 403
    assert ACCESS_URL not in response.get_data(as_text=True)


def test_missing_target_does_not_500(client, buyer, course):
    enrollment = _paid_enrollment(buyer, course)
    course.access_url = None
    db.session.commit()

    response = client.get(f'/online-courses/access/{enrollment.access_token}')
    assert response.status_code == 503


def test_open_is_recorded(client, buyer, course):
    enrollment = _paid_enrollment(buyer, course)
    client.get(f'/online-courses/access/{enrollment.access_token}')

    db.session.refresh(enrollment)
    assert enrollment.access_last_opened_at is not None


# ----------------------------- перевипуск -----------------------------

def test_reissue_gives_new_working_token(client, buyer, course):
    enrollment = _paid_enrollment(buyer, course)
    old_token = enrollment.access_token
    enrollment.access_expires_at = utcnow() - timedelta(hours=1)
    db.session.commit()
    _login(client, buyer)

    response = client.post(f'/online-courses/access/{enrollment.id}/reissue')
    assert response.status_code == 302

    db.session.refresh(enrollment)
    assert enrollment.access_token != old_token
    # Старий токен більше нікуди не веде.
    assert client.get(f'/online-courses/access/{old_token}').status_code == 404
    assert client.get(
        f'/online-courses/access/{enrollment.access_token}'
    ).status_code == 302


def test_reissue_of_someone_elses_order_is_404(client, buyer, course, app):
    enrollment = _paid_enrollment(buyer, course)
    stranger = User.create_with_password(
        f'str-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Хтось', last_name='Інший',
    )
    db.session.commit()
    _login(client, stranger)

    response = client.post(f'/online-courses/access/{enrollment.id}/reissue')
    assert response.status_code == 404


# ----------------------------- кабінет -----------------------------

def test_account_lists_purchased_course(client, buyer, course):
    _paid_enrollment(buyer, course)
    _login(client, buyer)

    body = client.get('/auth/account').get_data(as_text=True)
    assert 'Плазмотерапія' in body
    assert 'Мої онлайн-курси' in body


def test_account_offers_reissue_for_expired(client, buyer, course):
    enrollment = _paid_enrollment(buyer, course)
    enrollment.access_expires_at = utcnow() - timedelta(hours=1)
    db.session.commit()
    _login(client, buyer)

    body = client.get('/auth/account').get_data(as_text=True)
    assert 'reissue' in body


def test_account_shows_pending_state_when_not_provisioned(client, buyer, course):
    enrollment = OnlineEnrollment(
        user_id=buyer.id, online_course_id=course.id,
        payment_amount=Decimal('4500'), payment_status='paid', status='active',
    )
    db.session.add(enrollment)
    db.session.commit()
    _login(client, buyer)

    body = client.get('/auth/account').get_data(as_text=True)
    assert 'Доступ готується' in body


def test_account_never_exposes_access_url(client, buyer, course):
    _paid_enrollment(buyer, course)
    _login(client, buyer)

    body = client.get('/auth/account').get_data(as_text=True)
    assert 'secret-abc' not in body
