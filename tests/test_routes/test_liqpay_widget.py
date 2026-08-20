"""Оплата у вікні LiqPay: повернення на сайт без проміжної квитанції.

Головне, що тут стережеться, -- це НЕ віджет, а те, що форма лишається
робочою без нього. Віджет прибирає зайвий клік; зламана форма прибирає
оплату, і ціна помилки тут різна на порядки.
"""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from tests import refund_fixtures

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User


def _uid():
    return uuid4().hex[:6]


@pytest.fixture(autouse=True)
def clean(app):
    yield
    refund_fixtures.purge('lqw-', 'lqw-')


@pytest.fixture(autouse=True)
def liqpay_configured(app):
    """Ключі LiqPay -- інакше маршрут не будує платіжну форму взагалі."""
    settings = SiteSettings.get()
    before = (settings.liqpay_public_key, settings.liqpay_private_key,
              settings.liqpay_sandbox)
    settings.liqpay_public_key = 'sandbox_i000000000'
    settings.liqpay_private_key = 'sandbox_secret'
    settings.liqpay_sandbox = True
    db.session.flush()
    yield
    (settings.liqpay_public_key, settings.liqpay_private_key,
     settings.liqpay_sandbox) = before
    db.session.flush()


@pytest.fixture
def buyer(app):
    item = User.create_with_password(
        f'lqw-{_uid()}@test.com', 'password123',
        first_name='Ніна', last_name='Левченко', email_confirmed=True,
    )
    db.session.flush()
    return item


@pytest.fixture
def unpaid_reg(app, buyer):
    course = Course(title='Курс', slug=f'lqw-{_uid()}', is_active=False)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(course_id=course.id, status='published', price=1000,
                              start_date=utcnow() + timedelta(days=30))
    db.session.add(instance)
    db.session.flush()
    item = EventRegistration(
        user_id=buyer.id, instance_id=instance.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status='pending', payment_status='unpaid',
        payment_amount=Decimal('1000'),
    )
    db.session.add(item)
    db.session.flush()
    return item


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def test_csp_allows_the_widget_library(client):
    """Без цього домену браузер просто не завантажить checkout.js."""
    csp = client.get('/').headers.get('Content-Security-Policy', '')

    script_src = [p for p in csp.split('; ') if p.startswith('script-src')][0]
    assert 'https://static.liqpay.ua' in script_src


def test_csp_still_allows_the_payment_frames(client):
    csp = client.get('/').headers.get('Content-Security-Policy', '')

    assert 'https://www.liqpay.ua' in csp
    assert 'https://checkout.liqpay.ua' in csp


def test_payment_form_carries_widget_data(client, buyer, unpaid_reg):
    _login(client, buyer)

    body = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

    assert 'data-liqpay-form' in body
    assert 'data-liqpay-result-url=' in body
    assert 'js/liqpay-checkout.js' in body


def test_form_still_posts_to_liqpay_without_js(client, buyer, unpaid_reg):
    """Запасний шлях: атрибути атрибутами, а POST має лишитись POST-ом.

    Якщо скрипт не завантажиться, людина мусить оплатити старим способом --
    тому форма зберігає і action, і обидва підписані поля.
    """
    _login(client, buyer)

    body = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

    assert 'action="https://www.liqpay.ua/api/3/checkout"' in body
    assert 'name="data"' in body
    assert 'name="signature"' in body


def test_widget_result_url_matches_the_signed_one(client, buyer, unpaid_reg):
    """Віджет має вести туди ж, куди повів би сам LiqPay.

    `result_url` підписаний усередині `data`, а віджету він передається
    окремим атрибутом. Розбіжність означала б, що після оплати у вікні
    людина потрапляє не туди, куди при звичайному POST.
    """
    import base64
    import json
    import re

    _login(client, buyer)
    body = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

    signed = json.loads(base64.b64decode(
        re.search(r'name="data" value="([^"]+)"', body).group(1)))
    attr = re.search(r'data-liqpay-result-url="([^"]+)"', body).group(1)

    assert attr == signed['result_url']
    assert f'REG-{unpaid_reg.id}' in signed['order_id']


def test_paid_registration_has_no_payment_form(client, buyer, unpaid_reg):
    """Оплаченому замовленню платіжна форма не показується взагалі."""
    unpaid_reg.payment_status = 'paid'
    unpaid_reg.status = 'confirmed'
    db.session.flush()
    _login(client, buyer)

    body = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

    assert 'data-liqpay-form' not in body
