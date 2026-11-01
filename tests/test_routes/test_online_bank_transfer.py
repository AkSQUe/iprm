"""Оформлення онлайн-курсу: реквізити переказу з ONL-<id> і QR.

Рахунок за онлайн-курс має номер ONL-<id>, і за ним mm-medic зіставляє
переказ так само, як REG-. Тому там, де сторінка пропонує рахунок, вона
показує й те саме призначення з кнопкою «Копіювати» і той самий QR.
"""
import html as htmllib
import re
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services.payment_purpose import build_payment_purpose


@pytest.fixture
def settings(app):
    item = SiteSettings.get()
    before = (item.pay_liqpay_enabled, item.pay_invoice_enabled, item.bank_iban)
    yield item
    item.pay_liqpay_enabled, item.pay_invoice_enabled, item.bank_iban = before
    db.session.flush()


@pytest.fixture
def buyer(app):
    item = User.create_with_password(
        f'obt-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Олена', last_name='Береза', email_confirmed=True,
    )
    db.session.flush()
    return item


@pytest.fixture
def course(app):
    item = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Онлайн-курс',
        slug=f'obt-{uuid4().hex[:6]}',
        price=Decimal('3200'),
        access_url='https://example.test/register/x',
        is_published=True,
    )
    db.session.add(item)
    db.session.commit()
    yield item
    OnlineEnrollment.query.filter_by(online_course_id=item.id).delete()
    db.session.delete(item)
    db.session.commit()


@pytest.fixture
def enrollment(app, buyer, course):
    item = OnlineEnrollment(
        online_course_id=course.id, user_id=buyer.id,
        payment_status='unpaid', payment_amount=Decimal('3200'),
    )
    db.session.add(item)
    db.session.flush()
    return item


def _shown(page):
    """Текст без тегів і без вставлених пробілів (номер -- у span)."""
    return htmllib.unescape(re.sub(r'<[^>]+>', '', page))


def _page(client, buyer, course):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(buyer.id)
    return client.get(
        f'/online-courses/{course.slug}/checkout').get_data(as_text=True)


@pytest.mark.parametrize('liqpay_on', [True, False])
def test_unpaid_shows_onl_purpose_copy_and_qr(client, buyer, course, enrollment,
                                              settings, liqpay_on):
    """І поруч із LiqPay, і коли рахунок -- єдиний спосіб."""
    settings.pay_liqpay_enabled = liqpay_on
    db.session.flush()

    page = _page(client, buyer, course)

    purpose = build_payment_purpose(enrollment)
    assert f'ONL-{enrollment.id}' in purpose
    assert purpose in _shown(page)
    assert f'data-copy="{purpose}"' in htmllib.unescape(page)
    assert 'data-payment-qr' in page
    assert 'css/bank-transfer.css' in page


def test_paid_shows_no_requisites(client, buyer, course, enrollment):
    enrollment.payment_status = 'paid'
    db.session.flush()

    page = _page(client, buyer, course)

    assert 'bank-transfer' not in page


def test_invoice_method_off_shows_no_requisites(client, buyer, course,
                                                enrollment, settings):
    settings.pay_invoice_enabled = False
    db.session.flush()

    page = _page(client, buyer, course)

    assert 'bank-transfer' not in page


def test_bad_iban_keeps_text_drops_qr(client, buyer, course, enrollment,
                                      settings):
    settings.bank_iban = 'UA12'
    db.session.flush()

    page = _page(client, buyer, course)

    assert build_payment_purpose(enrollment) in _shown(page)
    assert 'data-payment-qr' not in page


@pytest.mark.parametrize('payment_status', ['pending', 'refunded'])
def test_pending_or_refunded_shows_no_requisites(client, buyer, course,
                                                 enrollment, payment_status):
    """pending -- гроші вже в дорозі, refunded -- їх повернули: переказ за
    тим самим ONL- був би другою оплатою, яку зарахувати нікуди."""
    enrollment.payment_status = payment_status
    db.session.flush()

    page = _page(client, buyer, course)

    assert 'bank-transfer' not in page
