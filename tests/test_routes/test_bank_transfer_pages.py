"""Реквізити переказу з призначенням і QR -- там, де учаснику кажуть
«сплатіть через банк».

Номер REG-<id> у призначенні -- те, за чим mm-medic зіставляє переказ із
реєстрацією одразу. Поки призначення жило лише в PDF, людина з телефона
переписувала реквізити як бачила, і номер губився. Тому сторінка показує
той самий рядок, що й рахунок, кнопку «Копіювати» і той самий QR.

Доплата різниці тарифу -- окремий платіж із власним номером SUR-<id>: для
mm-medic це сигнал «не зіставляти автоматично».
"""
import html as htmllib
import re
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from tests import refund_fixtures

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services.payment_purpose import (
    build_payment_purpose, build_surcharge_purpose,
)

PREFIX = 'btp-'
QR_MARKER = 'data-payment-qr'
COPY_MARKER = 'data-copy-reveal'


def _uid():
    return uuid4().hex[:6]


@pytest.fixture(autouse=True)
def _no_rate_limit():
    from app.extensions import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def clean(app):
    yield
    refund_fixtures.purge(PREFIX, PREFIX)


@pytest.fixture
def settings(app):
    """Способи оплати й IBAN з відновленням після тесту."""
    item = SiteSettings.get()
    before = (item.pay_liqpay_enabled, item.pay_invoice_enabled, item.bank_iban)
    yield item
    item.pay_liqpay_enabled, item.pay_invoice_enabled, item.bank_iban = before
    db.session.flush()


@pytest.fixture
def buyer(app):
    item = User.create_with_password(
        f'{PREFIX}{_uid()}@test.com', 'password123',
        first_name='Олена', last_name='Береза', email_confirmed=True,
    )
    db.session.flush()
    return item


@pytest.fixture
def instance(app):
    course = Course(title='Курс', slug=f'{PREFIX}{_uid()}', is_active=False)
    db.session.add(course)
    db.session.flush()
    item = CourseInstance(
        course_id=course.id, status='published', price=1000,
        start_date=utcnow() + timedelta(days=30),
    )
    db.session.add(item)
    db.session.flush()
    return item


@pytest.fixture
def unpaid_reg(app, buyer, instance):
    item = EventRegistration(
        user_id=buyer.id, instance_id=instance.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status='pending', payment_status='unpaid',
        payment_amount=Decimal('1000'), payment_method='invoice',
    )
    db.session.add(item)
    db.session.flush()
    return item


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def _text(page):
    """Видимий текст без тегів: призначення шукаємо як рядок, а не як HTML."""
    return htmllib.unescape(re.sub(r'<[^>]+>', ' ', page))


def _assert_transfer_block(page, purpose):
    assert 'bank-transfer' in page
    assert purpose in htmllib.unescape(page)
    assert f'data-copy="{purpose}"' in htmllib.unescape(page)
    assert COPY_MARKER in page
    assert QR_MARKER in page
    assert re.search(r'<img[^>]+src="data:image/svg\+xml[^"]*"[^>]+data-payment-qr', page)


class TestConfirmationPage:
    def test_unpaid_shows_purpose_copy_and_qr(self, client, buyer, unpaid_reg):
        _login(client, buyer)
        page = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

        purpose = build_payment_purpose(unpaid_reg)
        assert f'REG-{unpaid_reg.id}' in purpose
        _assert_transfer_block(page, purpose)

    def test_copy_button_hidden_without_js(self, client, buyer, unpaid_reg):
        """Без JS кнопка нічого не робить -- тому вона й не видна."""
        _login(client, buyer)
        page = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

        button = re.search(r'<button[^>]*data-copy-reveal[^>]*>', page).group(0)
        assert ' hidden' in button

    def test_paid_shows_no_requisites(self, client, buyer, unpaid_reg):
        unpaid_reg.payment_status = 'paid'
        db.session.flush()
        _login(client, buyer)
        page = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

        assert 'bank-transfer' not in page
        assert QR_MARKER not in page

    def test_invoice_method_off_shows_no_requisites(self, client, buyer, unpaid_reg,
                                                    settings):
        settings.pay_invoice_enabled = False
        db.session.flush()
        _login(client, buyer)
        page = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

        assert 'bank-transfer' not in page

    def test_bad_iban_keeps_text_drops_qr(self, client, buyer, unpaid_reg, settings):
        """Правило рахунка: QR, який банк відхилить, гірший за жоден."""
        settings.bank_iban = 'UA12'
        db.session.flush()
        _login(client, buyer)
        page = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

        assert build_payment_purpose(unpaid_reg) in htmllib.unescape(page)
        assert QR_MARKER not in page

    def test_component_css_linked_only_with_block(self, client, buyer, unpaid_reg):
        _login(client, buyer)
        page = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)
        assert 'css/bank-transfer.css' in page

        unpaid_reg.payment_status = 'paid'
        db.session.flush()
        page = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)
        assert 'css/bank-transfer.css' not in page


class TestTokenPayPage:
    def test_unpaid_shows_purpose_copy_and_qr(self, client, unpaid_reg):
        token = unpaid_reg.issue_completion_token()
        db.session.flush()

        page = client.get(f'/registration/complete/{token}/pay').get_data(as_text=True)

        _assert_transfer_block(page, build_payment_purpose(unpaid_reg))

    def test_paid_shows_no_requisites(self, client, unpaid_reg):
        token = unpaid_reg.issue_completion_token()
        unpaid_reg.payment_status = 'paid'
        db.session.flush()

        page = client.get(f'/registration/complete/{token}/pay').get_data(as_text=True)

        assert 'bank-transfer' not in page


class TestSurchargePage:
    @pytest.fixture
    def transfer(self, app, monkeypatch, buyer):
        from app.services import transfer_service

        monkeypatch.setattr(
            'app.services.email_service.EmailService.send_transfer_offer',
            staticmethod(lambda t: None),
        )
        course = Course(title='Курс переносу', slug=f'{PREFIX}tr-{_uid()}')
        db.session.add(course)
        db.session.flush()
        now = utcnow()
        src = CourseInstance(course_id=course.id, status='published',
                             start_date=now + timedelta(days=10), price=1000)
        dst = CourseInstance(course_id=course.id, status='published',
                             start_date=now + timedelta(days=20), price=1500)
        db.session.add_all([src, dst])
        db.session.flush()
        tariff = InstanceTariff(instance_id=dst.id, name='Практикум', price=1500)
        reg = EventRegistration(
            user_id=buyer.id, instance_id=src.id, phone='+380000000000',
            specialty='Лікар', workplace='Клініка', status='confirmed',
            payment_status='paid', payment_amount=1000,
        )
        db.session.add_all([tariff, reg])
        db.session.commit()
        return transfer_service.execute(
            reg, target_instance=dst, initiator='participant', tariff=tariff,
            tariff_decision='surcharge', announced=True,
        )

    def _page(self, client, transfer):
        return client.get(
            f'/registration/transfer/{transfer.consent_token}/surcharge',
        ).get_data(as_text=True)

    def test_liqpay_off_shows_sur_purpose_and_qr(self, client, transfer, settings):
        settings.pay_liqpay_enabled = False
        db.session.flush()

        page = self._page(client, transfer)

        purpose = build_surcharge_purpose(transfer)
        assert f'SUR-{transfer.id}' in purpose
        _assert_transfer_block(page, purpose)
        # Сума -- різниця тарифу, а не payment_amount реєстрації.
        assert '500' in _text(page)

    def test_surcharge_purpose_does_not_look_like_registration(self, client, transfer,
                                                               settings):
        """Старе «реєстрація №<id>» без SUR- mm-medic міг зарахувати за ПІБ і
        сумою не туди; номера REG- тут теж бути не може."""
        settings.pay_liqpay_enabled = False
        db.session.flush()

        text = _text(self._page(client, transfer))

        assert 'реєстрація №' not in text
        assert f'REG-{transfer.registration_id}' not in text

    def test_liqpay_form_means_no_requisites(self, client, transfer, settings,
                                             liqpay_keys):
        settings.pay_liqpay_enabled = True
        db.session.flush()

        page = self._page(client, transfer)

        assert 'bank-transfer' not in page
