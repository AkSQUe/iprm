"""Лист-пропозиція при перенесенні.

Головне, що тут перевіряється: порожні причина й примітка не дають ані
заголовка, ані порожнього блоку. Це прямий пункт технічного завдання.
"""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.email_log import EmailLog
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import transfer_service
from tests.refund_fixtures import purge

PREFIX = 'rte-'


@pytest.fixture
def world(app):
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    # flush ПЕРЕД set_password: воно вимагає persisted user (user.id), інакше
    # RuntimeError -- див. відому пастку з Task 1.
    db.session.flush()
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
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.commit()
    yield reg, dst
    purge(PREFIX, slug_prefix=PREFIX)


def test_transfer_trigger_is_allowed():
    """Інваріант TRIGGERS <-> ck_email_logs_trigger стереже
    test_all_code_triggers_are_allowed / test_check_constraint_matches_allowed_triggers
    (tests/test_services/test_email_service.py); тут перевіряємо саме новий код."""
    assert EmailLog.is_valid_trigger('transfer')


def test_offer_renders_reason_and_note(world, app):
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', reason='Тренер захворів',
        note='Місце проведення те саме', announced=False,
    )
    html = _render(app, transfer)
    assert 'Тренер захворів' in html
    assert 'Місце проведення те саме' in html


def test_offer_omits_empty_reason_and_note(world, app):
    """Порожні поля не мають лишати ані заголовка, ані порожнього блоку."""
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', announced=False,
    )
    html = _render(app, transfer)
    assert 'Причина перенесення' not in html
    assert 'Примітка' not in html


def test_offer_contains_both_choices(world, app):
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', announced=False,
    )
    transfer.issue_consent_token()
    db.session.commit()
    html = _render(app, transfer)
    assert f'/registration/transfer/{transfer.consent_token}' in html


def _render(app, transfer):
    from flask import render_template
    with app.test_request_context():
        from app.models.site_settings import SiteSettings
        return render_template(
            'emails/transfer_offer.html',
            user=transfer.registration.user,
            transfer=transfer,
            registration=transfer.registration,
            consent_url=f'https://example.com/registration/transfer/{transfer.consent_token}',
            surcharge_url=None,
            site_settings=SiteSettings.get(),
        )
