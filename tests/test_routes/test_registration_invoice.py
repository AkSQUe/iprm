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
