"""Роути перенесення в адмінці."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from tests.refund_fixtures import purge

PREFIX = 'rta-'


@pytest.fixture
def login_admin(client):
    def _login(admin):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
            sess['_fresh'] = True
    return _login


@pytest.fixture
def world(app):
    admin = User(email=f'{PREFIX}admin@example.com', first_name='Адмін',
                 last_name='Тестовий', is_active=True, is_admin=True)
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([admin, user, course])
    db.session.flush()
    # Пароль ставимо ЛИШЕ після flush: set_password() вимагає persisted
    # User (self.id), інакше падає RuntimeError.
    admin.set_password('x' * 12)
    user.set_password('x' * 12)
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=1500)
    soon = CourseInstance(course_id=course.id, status='published',
                          start_date=now + timedelta(hours=12), price=1500)
    db.session.add_all([src, dst, soon])
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.commit()
    yield {'admin': admin, 'reg': reg, 'src': src, 'dst': dst, 'soon': soon}
    purge(PREFIX, slug_prefix=PREFIX)


def test_options_requires_admin(client, world):
    resp = client.get(f"/admin/registrations/{world['reg'].id}/transfer/options")
    assert resp.status_code in (302, 401, 403)


def test_options_lists_only_eligible(client, world, login_admin):
    login_admin(world['admin'])
    resp = client.get(f"/admin/registrations/{world['reg'].id}/transfer/options")
    assert resp.status_code == 200
    ids = [row['id'] for row in resp.get_json()['instances']]
    assert world['dst'].id in ids
    assert world['src'].id not in ids
    assert world['soon'].id not in ids  # менше 2 діб


def test_options_reports_blockers(client, world, login_admin):
    login_admin(world['admin'])
    world['reg'].status = 'cancelled'
    db.session.commit()
    resp = client.get(f"/admin/registrations/{world['reg'].id}/transfer/options")
    data = resp.get_json()
    assert data['instances'] == []
    assert data['problems']


def test_transfer_moves_registration(client, world, login_admin):
    login_admin(world['admin'])
    reg = world['reg']
    resp = client.post(f'/admin/registrations/{reg.id}/transfer', data={
        'instance_id': world['dst'].id,
        'initiator': 'participant',
        'tariff_decision': 'keep',
        'reason': 'Прохання учасника',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(reg)
    assert reg.instance_id == world['dst'].id


def test_transfer_rejects_organizer_surcharge(client, world, login_admin):
    """§3.2 має відбиватись і роутом, а не лише CHECK-ом БД."""
    login_admin(world['admin'])
    reg = world['reg']
    client.post(f'/admin/registrations/{reg.id}/transfer', data={
        'instance_id': world['dst'].id,
        'initiator': 'organizer',
        'tariff_decision': 'surcharge',
    }, follow_redirects=True)
    db.session.refresh(reg)
    assert reg.instance_id == world['src'].id


def test_transfer_rejects_blocked(client, world, login_admin):
    login_admin(world['admin'])
    reg = world['reg']
    client.post(f'/admin/registrations/{reg.id}/transfer', data={
        'instance_id': world['soon'].id,
        'initiator': 'participant',
        'tariff_decision': 'keep',
    }, follow_redirects=True)
    db.session.refresh(reg)
    assert reg.instance_id == world['src'].id
