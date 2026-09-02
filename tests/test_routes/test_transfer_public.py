"""Публічні сторінки згоди на перенесення -- без входу, по токену."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.registration_transfer import RegistrationTransfer
from app.models.user import User
from app.services import transfer_service
from tests.refund_fixtures import purge

PREFIX = 'rtp-'


@pytest.fixture
def offer(app, monkeypatch):
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda transfer: None),
    )
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    db.session.flush()
    # set_password() вимагає persisted User (self.id) -- викликаємо
    # після flush, інакше падає RuntimeError.
    user.set_password('x' * 12)
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=1000)
    db.session.add_all([src, dst])
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='pending',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.commit()
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', announced=True,
    )
    yield transfer, reg
    purge(PREFIX, slug_prefix=PREFIX)


def test_page_opens_without_login(client, offer):
    transfer, _reg = offer
    resp = client.get(f'/registration/transfer/{transfer.consent_token}')
    assert resp.status_code == 200


def test_unknown_token_is_404(client, offer):
    resp = client.get('/registration/transfer/definitely-not-a-token')
    assert resp.status_code == 404


def test_expired_token_is_rejected(client, offer):
    transfer, _reg = offer
    transfer.consent_token_expires_at = utcnow() - timedelta(days=1)
    db.session.commit()
    resp = client.get(f'/registration/transfer/{transfer.consent_token}')
    assert resp.status_code == 404


def test_accept_confirms(client, offer):
    transfer, reg = offer
    resp = client.post(
        f'/registration/transfer/{transfer.consent_token}/accept',
        follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(transfer)
    db.session.refresh(reg)
    assert transfer.state == RegistrationTransfer.STATE_ACCEPTED
    assert reg.status == 'confirmed'


def test_refund_opens_request(client, offer):
    from app.models.refund_request import RefundRequest
    transfer, reg = offer
    resp = client.post(
        f'/registration/transfer/{transfer.consent_token}/refund',
        data={'reason': 'Дата не підходить'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(transfer)
    assert transfer.state == RegistrationTransfer.STATE_REFUND_REQUESTED
    request = RefundRequest.query.filter_by(registration_id=reg.id).one()
    assert request.quoted_percent == 100


def test_refund_requires_reason(client, offer):
    from app.models.refund_request import RefundRequest
    transfer, reg = offer
    client.post(f'/registration/transfer/{transfer.consent_token}/refund',
                data={'reason': '   '}, follow_redirects=True)
    db.session.refresh(transfer)
    assert transfer.state == RegistrationTransfer.STATE_AWAITING
    assert RefundRequest.query.filter_by(registration_id=reg.id).count() == 0


def test_second_answer_is_refused(client, offer):
    transfer, _reg = offer
    client.post(f'/registration/transfer/{transfer.consent_token}/accept',
                follow_redirects=True)
    client.post(f'/registration/transfer/{transfer.consent_token}/refund',
                data={'reason': 'Передумав'}, follow_redirects=True)
    db.session.refresh(transfer)
    assert transfer.state == RegistrationTransfer.STATE_ACCEPTED
