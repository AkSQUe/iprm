"""Фонова звірка зависли платежів.

Кнопка в адмінці рятує від аварії, про яку вже знають. Ця джоба -- від тієї,
якої ніхто не помітив: колбек від LiqPay загубився, платник більше не зайшов
на сторінку оплати, і замовлення тихо висить у `pending` разом із листом про
оплату, подією партнеру й вивозом у KeyCRM.

Тестується внутрішня функція, а не обгортка: обгортка бере
`pg_try_advisory_lock`, якого в SQLite немає. Той самий поділ і з тієї ж
причини вже вжито для `_send_online_access_reminders`.
"""
import logging
from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import scheduler_service


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def instance(app):
    owner = User.create_with_password(
        f'job-own-{_uid()}@test.com', 'password123',
        first_name='O', last_name='W',
    )
    db.session.flush()
    course = Course(
        title='Курс', slug=f'job-{_uid()}', event_type='course',
        base_price=1000, is_active=False, created_by=owner.id,
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='active', event_format='offline', price=1000,
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _stuck(instance, age_days=0):
    buyer = User.create_with_password(
        f'job-{_uid()}@test.com', 'password123', first_name='B', last_name='U',
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=buyer.id, instance_id=instance.id,
        phone='+380000000000', specialty='Х', workplace='Л',
        status='pending', payment_status='pending', payment_amount=1000,
    )
    if age_days:
        reg.created_at = utcnow() - timedelta(days=age_days)
    db.session.add(reg)
    db.session.flush()
    return reg


def _liqpay(monkeypatch, status='success', configured=True):
    service = MagicMock()
    service.is_configured = configured
    service.check_status.return_value = {
        'status': status, 'payment_id': f'PAY-{_uid()}', 'amount': 1000,
    }
    monkeypatch.setattr('app.services.liqpay.get_liqpay_service',
                        lambda: service)
    return service


def test_resolves_a_fresh_stuck_payment(app, instance, monkeypatch):
    _liqpay(monkeypatch, 'success')
    reg = _stuck(instance)

    scheduler_service._reconcile_stuck_payments()

    assert reg.payment_status == 'paid'
    assert reg.status == 'confirmed'


def test_leaves_long_dead_rows_alone(app, instance, monkeypatch):
    """Замовлення, яке не зрушить ніколи (людина заплатила за рахунком),
    не має ставати вічним запитом до чужого API кожні 15 хвилин."""
    service = _liqpay(monkeypatch, 'wait_accept')
    _stuck(instance, age_days=30)

    scheduler_service._reconcile_stuck_payments()

    service.check_status.assert_not_called()


def test_quiet_when_nothing_is_stuck(app, monkeypatch, caplog):
    """Джоба, яка щочверть години пише «нічого», навчає читати лог по
    діагоналі -- і саме тоді пропускають рядок, що має значення."""
    _liqpay(monkeypatch, 'success')

    with caplog.at_level(logging.INFO, logger='app.services.scheduler_service'):
        scheduler_service._reconcile_stuck_payments()

    assert caplog.records == []


def test_unconfigured_liqpay_is_not_an_error(app, instance, monkeypatch, caplog):
    """Ключі можуть бути ще не збережені. Це стан налаштування, а не збій:
    ERROR щочверть години зробив би тривогу фоновим шумом."""
    _liqpay(monkeypatch, configured=False)
    _stuck(instance)

    with caplog.at_level(logging.INFO, logger='app.services.scheduler_service'):
        scheduler_service._reconcile_stuck_payments()

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_wrapper_exists_for_the_scheduler(app):
    """Обгортка -- те, що реєструється в планувальнику. Без неї джоба
    зареєстрована бути не може."""
    assert callable(getattr(scheduler_service, 'reconcile_stuck_payments', None))
