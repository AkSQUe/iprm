# flake8: noqa: F811
"""Сертифікат після подачі звіту до Центру тестування.

Новий не видається ні тестом, ні вручну: реєстр БПР уже закрито. Але
відкликаний сертифікат, що вже пішов у реєстр, можна видати знову -- з тим
самим номером.
"""
from datetime import date, datetime, timezone

import pytest

from app.extensions import db
from app.services import certificate_service
from tests.test_services.test_certificate_number import (  # noqa: F401
    _registration, bpr_settings, no_pdf,
)


def test_issue_refused_after_report(app, no_pdf):
    reg = _registration()
    reg.instance.bpr_report_submitted_on = date.today()
    db.session.flush()

    with pytest.raises(ValueError, match='Звіт до Центру тестування'):
        certificate_service.issue_certificate(reg)
    assert reg.certificate is None


def test_revoked_reissued_after_report_keeps_number(app, no_pdf):
    reg = _registration()
    cert = certificate_service.issue_certificate(reg)
    number = cert.number
    cert.revoked = True
    cert.revoked_at = datetime.now(timezone.utc)
    reg.instance.bpr_report_submitted_on = date.today()
    db.session.flush()

    again = certificate_service.issue_certificate(reg)
    assert again.number == number
    assert again.revoked is False


def test_valid_certificate_returned_after_report(app, no_pdf):
    reg = _registration()
    cert = certificate_service.issue_certificate(reg)
    reg.instance.bpr_report_submitted_on = date.today()
    db.session.flush()

    assert certificate_service.issue_certificate(reg).id == cert.id


def test_passed_before_report_without_certificate_can_still_be_issued(app, no_pdf):
    reg = _registration()
    reg.quiz_passed_at = datetime.now(timezone.utc)
    reg.instance.bpr_report_submitted_on = date.today()
    db.session.flush()

    assert certificate_service.issue_certificate(reg).number
