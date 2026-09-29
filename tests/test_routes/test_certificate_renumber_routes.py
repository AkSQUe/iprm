"""Кнопка «Перенумерувати» в картці проведення.

Блок видно лише там, де номери заходу не йдуть по порядку; дія переписує
номери й розсилає учасникам оновлені сертифікати (у фоні -- тут підмінено).
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import certificate_service
from tests.support.rbac import make_super_admin


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin_client(client):
    user = make_super_admin(email=f'renum-adm-{_uid()}@test.com')
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    return client


@pytest.fixture
def mailed(monkeypatch):
    """Фонова розсилка в тестах не стартує; що її звали -- видно зі списку."""
    calls = []
    monkeypatch.setattr(certificate_service, 'email_certificates_in_background',
                        lambda ids: calls.append(sorted(ids)))
    monkeypatch.setattr(certificate_service, '_discard_stale_pdf',
                        lambda path, keep=None: None)
    return calls


@pytest.fixture
def instance(app):
    SiteSettings.get().bpr_provider_number = '2738'
    course = Course(title='Курс', slug=f'renumr-{_uid()}', is_active=True,
                    cpd_points_online=12, cpd_points_offline=12,
                    bpr_event_number=str(1700000 + int(_uid(), 16) % 99999))
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ', start_date=datetime(2026, 9, 12, 9, tzinfo=timezone.utc),
    )
    db.session.add(inst)
    db.session.commit()
    return inst


def _cert(instance, segment):
    user = User.create_with_password(
        f'renumr-{_uid()}@test.com', 'password123',
        first_name='Тест', last_name='Учасник', email_confirmed=True)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='completed',
        payment_status='paid', attended=True)
    db.session.add(reg)
    db.session.flush()
    number = Certificate.format_number(
        2026, '2738', instance.effective_bpr_event_number, segment)
    cert = Certificate(registration_id=reg.id, user_id=user.id, number=number,
                       recipient_name='Тест Учасник', event_title='Захід',
                       pdf_path=f'2026/{number}.pdf')
    db.session.add(cert)
    db.session.commit()
    return cert


def _card(client, instance):
    return client.get(f'/admin/instances/{instance.id}/edit').get_data(as_text=True)


def test_card_shows_the_block_only_when_numbers_are_out_of_order(admin_client,
                                                                 instance):
    _cert(instance, 1)
    assert 'certificates/renumber' not in _card(admin_client, instance)

    _cert(instance, 7)
    body = _card(admin_client, instance)
    assert 'certificates/renumber' in body
    assert body.count('-000007') == 1  # «Зараз»
    assert '-000002' in body           # «Стане»


def test_renumber_rewrites_numbers_and_mails_participants(admin_client, instance,
                                                          mailed):
    first, second = _cert(instance, 7), _cert(instance, 8)

    response = admin_client.post(
        f'/admin/instances/{instance.id}/certificates/renumber',
        follow_redirects=True)

    assert response.status_code == 200
    assert 'Перенумеровано сертифікатів: 2' in response.get_data(as_text=True)
    db.session.refresh(first)
    db.session.refresh(second)
    assert first.number.endswith('-000001')
    assert second.number.endswith('-000002')
    assert mailed == [sorted([first.id, second.id])]


def test_renumber_of_ordered_event_is_a_no_op(admin_client, instance, mailed):
    _cert(instance, 1)

    response = admin_client.post(
        f'/admin/instances/{instance.id}/certificates/renumber',
        follow_redirects=True)

    assert 'уже йдуть по порядку' in response.get_data(as_text=True)
    assert mailed == []


def test_renumber_needs_the_permission(client, instance, mailed):
    cert = _cert(instance, 7)
    viewer = User.create_with_password(
        f'renumr-view-{_uid()}@test.com', 'password123',
        first_name='В', last_name='Ю', email_confirmed=True)
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(viewer.id)

    response = client.post(f'/admin/instances/{instance.id}/certificates/renumber')

    assert response.status_code in (302, 403)
    db.session.refresh(cert)
    assert cert.number.endswith('-000007')
    assert mailed == []
