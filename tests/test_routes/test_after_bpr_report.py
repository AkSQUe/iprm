# flake8: noqa: F811
"""Маршрути після подачі звіту до Центру тестування.

Спроба, розпочата до подачі, не дає здати тест; ручна видача нового
сертифіката повертає зрозуміле повідомлення, а не 500; кнопка «Видати
сертифікат» зникає, коли запису про сертифікат немає зовсім.
"""
from datetime import date
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.quiz_attempt import QuizAttempt
from app.models.registration import EventRegistration
from app.models.user import User
from tests.support.rbac import grant_role
from tests.test_routes.test_quiz import (  # noqa: F401
    _answer_all, _login, _setup, bpr_ready, no_pdf,
)


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'rep-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='A', last_name='B', email_confirmed=True)
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


def test_submit_after_report_gives_no_score_and_no_certificate(client, app, no_pdf):
    reg, _ = _setup()
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)
    reg.instance.bpr_report_submitted_on = date.today()
    db.session.commit()

    resp = client.post(f'/quiz/attempt/{attempt.id}/submit')

    assert resp.status_code == 302
    db.session.expire_all()
    fresh = db.session.get(EventRegistration, reg.id)
    assert db.session.get(QuizAttempt, attempt.id).submitted_at is None
    assert fresh.quiz_passed_at is None
    assert Certificate.query.filter_by(registration_id=reg.id).count() == 0


def test_start_page_explains_closed_quiz(client, app):
    reg, _ = _setup()
    reg.instance.bpr_report_submitted_on = date.today()
    db.session.commit()
    _login(client, reg.user)

    html = client.get(f'/quiz/{reg.id}').get_data(as_text=True)

    assert 'подано до Центру тестування' in html


def test_manual_issue_after_report_is_flashed_not_500(client, app, admin, no_pdf):
    reg, _ = _setup()
    reg.instance.bpr_report_submitted_on = date.today()
    db.session.commit()
    _login(client, admin)

    resp = client.post(f'/admin/registrations/{reg.id}/certificate',
                       follow_redirects=True)

    assert resp.status_code == 200
    assert 'новий сертифікат видати не можна' in resp.get_data(as_text=True)
    assert Certificate.query.filter_by(registration_id=reg.id).count() == 0


def _issue_button_shown(client, reg):
    html = client.get(
        f'/admin/instances/{reg.instance_id}/registrations').get_data(as_text=True)
    return 'Видати сертифікат' in html


def test_issue_button_hidden_after_report_without_certificate(client, app, admin):
    reg, _ = _setup()
    _login(client, admin)
    assert _issue_button_shown(client, reg) is True

    reg.instance.bpr_report_submitted_on = date.today()
    db.session.commit()
    assert _issue_button_shown(client, reg) is False


def test_issue_button_stays_for_revoked_certificate_after_report(
        client, app, admin, no_pdf):
    from app.services import certificate_service
    reg, _ = _setup()
    cert = certificate_service.issue_certificate(reg)
    cert.revoked = True
    reg.instance.bpr_report_submitted_on = date.today()
    db.session.commit()
    _login(client, admin)

    assert _issue_button_shown(client, reg) is True
