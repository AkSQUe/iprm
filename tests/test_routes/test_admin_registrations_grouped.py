"""Режим «За заходами»: фрагмент учасників і заголовки груп."""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'grp-adm-{_uid()}@test.com', 'password123',
        first_name='А', last_name='Д', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.flush()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _course(title=None):
    course = Course(
        title=title or f'Курс {_uid()}', slug=f'grp-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, days=14):
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _registration(inst, status='confirmed', payment_status='paid', amount=3500):
    user = User.create_with_password(
        f'grp-{_uid()}@test.com', 'password123', first_name='У', last_name='Ч')
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380670000000',
        specialty='T', workplace='Клініка', status=status,
        payment_status=payment_status, payment_amount=amount,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


@pytest.fixture
def event_with_two_people(app):
    course = _course()
    inst = _instance(course)
    regs = [
        _registration(inst, 'confirmed', 'paid', 3500),
        _registration(inst, 'pending', 'unpaid', 2975),
    ]
    return course, inst, regs


def test_rows_fragment_returns_only_its_event(client, admin, event_with_two_people):
    _, inst, regs = event_with_two_people
    other = _instance(_course(), days=21)
    stranger = _registration(other)
    _login(client, admin)

    html = client.get(
        f'/admin/registrations/group/{inst.id}/rows').get_data(as_text=True)

    for reg in regs:
        assert f'/admin/registrations/{reg.id}/edit' in html
    assert f'/admin/registrations/{stranger.id}/edit' not in html


def test_rows_fragment_honours_filters(client, admin, event_with_two_people):
    _, inst, regs = event_with_two_people
    pending = next(r for r in regs if r.status == 'pending')
    confirmed = next(r for r in regs if r.status == 'confirmed')
    _login(client, admin)

    html = client.get(
        f'/admin/registrations/group/{inst.id}/rows?status=pending'
    ).get_data(as_text=True)

    assert f'/admin/registrations/{pending.id}/edit' in html
    assert f'/admin/registrations/{confirmed.id}/edit' not in html


def test_rows_fragment_returns_to_the_open_panel(client, admin, event_with_two_people):
    """Дія в рядку мусить повертати на ТУ САМУ розгорнуту панель."""
    _, inst, _ = event_with_two_people
    back = f'/admin/registrations?view=grouped&open={inst.id}'
    _login(client, admin)

    html = client.get(
        f'/admin/registrations/group/{inst.id}/rows?back={quote(back, safe="")}'
    ).get_data(as_text=True)

    assert f'open={inst.id}' in html


def test_rows_fragment_rejects_foreign_back(client, admin, event_with_two_people):
    """`back` іде у приховане поле `next`, тобто в редірект: чужий хост -- ні."""
    _, inst, _ = event_with_two_people
    _login(client, admin)

    html = client.get(
        f'/admin/registrations/group/{inst.id}/rows?back=https://evil.test/x'
    ).get_data(as_text=True)

    assert 'evil.test' not in html


def test_rows_fragment_requires_permission(client, app, event_with_two_people):
    """Фрагмент -- ті самі дані, що й сторінка, отже й ті самі права."""
    _, inst, _ = event_with_two_people
    stranger = User.create_with_password(
        f'grp-nop-{_uid()}@test.com', 'password123',
        first_name='Б', last_name='П', email_confirmed=True,
    )
    db.session.flush()
    _login(client, stranger)

    response = client.get(f'/admin/registrations/group/{inst.id}/rows')

    assert response.status_code in (302, 403)
