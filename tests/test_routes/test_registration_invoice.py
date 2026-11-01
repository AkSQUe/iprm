"""Tests for participant invoice download route (registration.invoice_download).

render_invoice_pdf мокаємо, щоб тест не залежав від нативних бібліотек
WeasyPrint -- перевіряємо лише логіку доступу/стану роуту.
"""
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def user(app):
    u = User.create_with_password(
        f'inv-{_uid()}@test.com', 'password123', first_name='Inv', last_name='User',
    )
    db.session.flush()
    return u


@pytest.fixture
def instance(app, user):
    c = Course(
        title='Invoice Course', slug=f'inv-course-{_uid()}',
        event_type='course', base_price=2500, is_active=True, created_by=user.id,
    )
    db.session.add(c)
    db.session.flush()
    inst = CourseInstance(
        course_id=c.id, status='active', event_format='offline', price=2500,
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _make_reg(user, instance, **kw):
    defaults = dict(
        user_id=user.id, instance_id=instance.id,
        phone='+380000000000', specialty='Test', workplace='Test',
        status='pending', payment_status='unpaid', payment_amount=2500,
    )
    defaults.update(kw)
    reg = EventRegistration(**defaults)
    db.session.add(reg)
    db.session.flush()
    return reg


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def _url(reg):
    return f'/registration/{reg.id}/invoice.pdf'


class TestInvoiceDownload:
    def test_unauthenticated_redirects(self, client, user, instance):
        reg = _make_reg(user, instance)
        resp = client.get(_url(reg))
        assert resp.status_code in (302, 401)

    def test_other_users_registration_404(self, client, user, instance):
        reg = _make_reg(user, instance)
        other = User.create_with_password(
            f'other-{_uid()}@test.com', 'password123', first_name='O', last_name='U',
        )
        db.session.flush()
        _login(client, other)
        resp = client.get(_url(reg))
        assert resp.status_code == 404

    def test_zero_amount_404(self, client, user, instance):
        reg = _make_reg(user, instance, payment_amount=0)
        _login(client, user)
        resp = client.get(_url(reg))
        assert resp.status_code == 404

    def test_paid_redirects_without_pdf(self, client, user, instance):
        reg = _make_reg(user, instance, payment_status='paid')
        _login(client, user)
        resp = client.get(_url(reg))
        assert resp.status_code == 302
        assert f'/registration/{reg.id}' in resp.headers['Location']

    @patch('app.services.invoice_service.render_invoice_pdf', return_value=b'%PDF-1.4 test')
    def test_unpaid_returns_pdf(self, mock_render, client, user, instance):
        reg = _make_reg(user, instance, payment_method='invoice')
        _login(client, user)
        resp = client.get(_url(reg))
        assert resp.status_code == 200
        assert resp.mimetype == 'application/pdf'
        assert resp.data == b'%PDF-1.4 test'
        mock_render.assert_called_once()


class TestInvoiceContent:
    """Призначення платежу, номер REG-/ONL- і QR у документах рахунка."""

    def test_pdf_context_has_purpose_number_and_qr(self, app, user, instance):
        from app.services.invoice_service import _invoice_template_ctx

        reg = _make_reg(user, instance)
        ctx = _invoice_template_ctx(reg)

        assert ctx['number'] == f'REG-{reg.id}'
        assert ctx['purpose'].startswith(f'Оплата згідно рахунку № REG-{reg.id} від ')
        assert ctx['purpose'].endswith('за User Inv')
        assert ctx['qr_data_uri'].startswith('data:image/svg+xml')

    def test_qr_skipped_on_bad_iban(self, app, user, instance):
        from app.models.site_settings import SiteSettings
        from app.services.invoice_service import (
            _invoice_template_ctx, render_invoice_pdf,
        )

        SiteSettings.get().bank_iban = 'UA12'
        reg = _make_reg(user, instance)

        assert _invoice_template_ctx(reg)['qr_data_uri'] is None
        assert render_invoice_pdf(reg)[:4] == b'%PDF'

    def test_html_shows_purpose_and_number(self, app, user, instance):
        from flask import render_template
        from app.services.invoice_service import _invoice_template_ctx

        reg = _make_reg(user, instance)
        ctx = _invoice_template_ctx(reg)
        html = render_template('invoices/invoice.html', **ctx)

        assert f'REG-{reg.id}' in html
        assert ctx['purpose'] in html
        assert 'Скануйте в застосунку банку' in html

    def test_pdf_renders(self, app, user, instance):
        from app.services.invoice_service import render_invoice_pdf

        assert len(render_invoice_pdf(_make_reg(user, instance))) > 0

    def test_xlsx_has_purpose_row(self, app, user, instance):
        from openpyxl import load_workbook
        from app.services.invoice_service import build_invoice_xlsx

        reg = _make_reg(user, instance)
        ws = load_workbook(build_invoice_xlsx(reg)).active
        values = [str(c.value) for row in ws.iter_rows() for c in row if c.value]

        from app.services.payment_purpose import build_payment_purpose

        # Сама КОМІРКА призначення (колонка значень), а не підпис у шапці.
        assert ws.cell(row=self._purpose_row(ws), column=3).value == (
            build_payment_purpose(reg))
        assert any(f'Оплата згідно рахунку № REG-{reg.id}' in v for v in values)
        assert any(v.startswith(f'№ REG-{reg.id} від') for v in values)

    @staticmethod
    def _purpose_row(ws):
        return next(c.row for c in ws['A'] if c.value == 'Призначення платежу')

    def test_xlsx_purpose_row_grows_with_long_text(self, app, user, instance):
        """Фіксована висота різала б довге призначення: висота рядка
        рахується від довжини тексту."""
        import math
        from openpyxl import load_workbook
        from app.services.invoice_service import build_invoice_xlsx
        from app.services.payment_purpose import build_payment_purpose

        user.first_name = 'Олександр-Іванович-Петрович'
        user.last_name = 'Прізвище-Подвійне-Дуже-Довге-Складне'
        reg = _make_reg(user, instance)
        purpose = build_payment_purpose(reg)
        ws = load_workbook(build_invoice_xlsx(reg)).active
        row = self._purpose_row(ws)

        assert ws.cell(row=row, column=3).value == purpose
        # Ширина C:F -- 44 символи; на рядок беремо менше, бо шрифт жирний.
        assert ws.row_dimensions[row].height >= 15 * math.ceil(len(purpose) / 44)
        assert ws.cell(row=row, column=3).alignment.wrap_text

    def test_filename_uses_order_ref(self, app, user, instance):
        from app.services.invoice_service import invoice_filename

        reg = _make_reg(user, instance)
        assert f'REG-{reg.id}' in invoice_filename(reg, 'pdf')
