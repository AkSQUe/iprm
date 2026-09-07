"""Рахунок у листі «Реєстрацію підтверджено».

Коли оплата йде на розрахунковий рахунок, PDF їде вкладенням: інакше
єдине, що людина отримує після реєстрації, -- це прохання зайти на сайт
і завантажити документ самотужки.

Окремо стережеться те, що збій PDF-рендера не забирає з собою лист.
WeasyPrint тягне нативні бібліотеки і на сервері падає не там, де його
тестували; лист про реєстрацію -- єдине підтвердження, яке має людина,
і втратити його через недоступний рендер гірше, ніж втратити вкладення.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services.email_service import EmailService
from app.services.invoice_service import InvoiceError

PDF = b'%PDF-1.4 fake'


def _uid():
    return uuid4().hex[:6]


@pytest.fixture
def buyer(app):
    item = User.create_with_password(
        f'inve-{_uid()}@test.com', 'password123',
        first_name='Оксана', last_name='Гриценко', email_confirmed=True,
    )
    db.session.flush()
    return item


@pytest.fixture
def registration(app, buyer):
    course = Course(title='Курс', slug=f'inve-{_uid()}', is_active=False)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='published', price=1000,
        start_date=utcnow() + timedelta(days=30),
    )
    db.session.add(instance)
    db.session.flush()
    item = EventRegistration(
        user_id=buyer.id, instance_id=instance.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status='pending', payment_status='unpaid',
        payment_amount=Decimal('1000'), payment_method='invoice',
    )
    db.session.add(item)
    db.session.flush()
    return item


def _attachments_of(send_email_mock):
    """Вкладення, з якими пішов сам лист про реєстрацію.

    send_registration_confirmation шле ще й сповіщення адмінам через той
    самий send_email, тож беремо саме виклик із потрібним шаблоном.
    """
    for call in send_email_mock.call_args_list:
        if call.kwargs.get('template_name') == 'registration_confirmed':
            return call.kwargs.get('attachments')
    raise AssertionError('Лист про реєстрацію не надсилався')


class TestInvoiceAttachment:
    @patch('app.services.email_service.EmailService.send_email')
    @patch('app.services.invoice_service.render_invoice_pdf', return_value=PDF)
    def test_invoice_method_attaches_pdf(self, render, send_email, registration):
        EmailService.send_registration_confirmation(registration)

        attachments = _attachments_of(send_email)

        assert attachments, 'рахунок мав поїхати вкладенням'
        filename, mimetype, data = attachments[0]
        assert filename.endswith('.pdf')
        assert mimetype == 'application/pdf'
        assert data == PDF

    @patch('app.services.email_service.EmailService.send_email')
    @patch('app.services.invoice_service.render_invoice_pdf', return_value=PDF)
    def test_liqpay_method_attaches_nothing(self, render, send_email, registration):
        registration.payment_method = 'liqpay'
        db.session.flush()

        EmailService.send_registration_confirmation(registration)

        assert not _attachments_of(send_email)
        render.assert_not_called()

    @patch('app.services.email_service.EmailService.send_email')
    @patch('app.services.invoice_service.render_invoice_pdf', return_value=PDF)
    def test_paid_registration_attaches_nothing(self, render, send_email, registration):
        """Оплаченій реєстрації рахунок ні до чого."""
        registration.payment_status = 'paid'
        db.session.flush()

        EmailService.send_registration_confirmation(registration)

        assert not _attachments_of(send_email)
        render.assert_not_called()

    @patch('app.services.email_service.EmailService.send_email')
    @patch('app.services.invoice_service.render_invoice_pdf', return_value=PDF)
    def test_free_registration_attaches_nothing(self, render, send_email, registration):
        registration.payment_amount = Decimal('0')
        db.session.flush()

        EmailService.send_registration_confirmation(registration)

        assert not _attachments_of(send_email)
        render.assert_not_called()

    @patch('app.services.email_service.EmailService.send_email')
    @patch('app.services.invoice_service.render_invoice_pdf',
           side_effect=InvoiceError('WeasyPrint недоступний'))
    def test_render_failure_still_sends_letter(self, render, send_email, registration):
        """Лист важливіший за вкладення -- він єдине підтвердження."""
        EmailService.send_registration_confirmation(registration)

        assert _attachments_of(send_email) is None

    @patch('app.services.email_service.EmailService.send_email')
    @patch('app.services.invoice_service.render_invoice_pdf', return_value=PDF)
    def test_invoice_method_disabled_attaches_nothing(self, render, send_email,
                                                      registration):
        """Спосіб вимкнено -- рахунка немає ніде, зокрема й у пошті."""
        settings = SiteSettings.get()
        before = settings.pay_invoice_enabled
        settings.pay_invoice_enabled = False
        db.session.flush()
        try:
            EmailService.send_registration_confirmation(registration)

            assert not _attachments_of(send_email)
            render.assert_not_called()
        finally:
            settings.pay_invoice_enabled = before
            db.session.flush()
