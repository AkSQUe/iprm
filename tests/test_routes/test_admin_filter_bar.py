"""Панель фільтрів: згортання, чіпси, діапазон дат і розмір сторінки.

Макрос `admin/partials/_filter_bar.html` спільний для всіх реєстрів, тож
поведінку перевіряємо на одному-двох представниках, а не на кожній сторінці.
"""
import re
from datetime import datetime, timedelta, timezone
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
def admin(app):
    u = User.create_with_password(
        f'fb-{_uid()}@test.com', 'password123',
        first_name='F', last_name='B', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


@pytest.fixture
def regs(app, admin):
    """Дві реєстрації: торішня і сьогоднішня -- для перевірки діапазону."""
    course = Course(title='Фільтри', slug=f'fb-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    made = []
    for age_days in (400, 0):
        inst = CourseInstance(course_id=course.id, status='published',
                              event_format='offline')
        db.session.add(inst)
        db.session.flush()
        user = User.create_with_password(
            f'fb-{_uid()}@test.com', 'password123',
            first_name='Учасник', last_name=f'Тест{age_days}',
            email_confirmed=True,
        )
        db.session.flush()
        reg = EventRegistration(
            user_id=user.id, instance_id=inst.id, phone='+380670000001',
            specialty='T', workplace='T', status='confirmed',
            payment_status='paid',
        )
        reg.created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
        db.session.add(reg)
        db.session.flush()
        made.append(reg)
    return {'old': made[0], 'fresh': made[1]}


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _panel_tag(html):
    m = re.search(r'<div class="admin-filters__panel".*?>', html, re.S)
    return m.group(0) if m else ''


def test_panel_is_collapsed_until_a_filter_is_set(client, admin):
    """Без фільтрів панель згорнута: менеджер приходить читати список."""
    _login(client, admin)
    plain = client.get('/admin/users').get_data(as_text=True)
    assert 'hidden' in _panel_tag(plain)
    assert 'admin-filters--on' not in plain

    filtered = client.get('/admin/users?role=admin').get_data(as_text=True)
    assert 'hidden' not in _panel_tag(filtered)
    # Активний зріз позначено і на самій панелі (кант + лічильник).
    assert 'admin-filters--on' in filtered
    assert 'admin-filters__count' in filtered


def test_chip_removes_only_its_own_filter(client, admin):
    _login(client, admin)
    html = client.get('/admin/users?role=admin&q=test').get_data(as_text=True)
    chips = re.findall(r'<a class="admin-chip" href="([^"]+)"', html)
    assert len(chips) == 2
    hrefs = [c.replace('&amp;', '&') for c in chips]
    # Чіпс пошуку веде на URL без q, але з role -- і навпаки.
    assert any('q=test' not in h and 'role=admin' in h for h in hrefs)
    assert any('role=admin' not in h and 'q=test' in h for h in hrefs)
    assert '<a class="admin-filters__reset" href="/admin/users">' in html


def test_date_range_narrows_by_kyiv_day(client, admin, regs):
    """Діапазон включає обидві межі за київською добою."""
    _login(client, admin)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    fresh_email = regs['fresh'].user.email
    old_email = regs['old'].user.email

    only_today = client.get(
        f'/admin/registrations?scope=all&date_from={today}').get_data(as_text=True)
    assert fresh_email in only_today
    assert old_email not in only_today

    until_yesterday = client.get(
        '/admin/registrations?scope=all&date_to='
        + (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
    ).get_data(as_text=True)
    assert old_email in until_yesterday
    assert fresh_email not in until_yesterday


def test_broken_date_is_ignored(client, admin, regs):
    """Сміття замість дати не ламає сторінку і не ховає список."""
    _login(client, admin)
    html = client.get(
        '/admin/registrations?scope=all&date_from=НЕ-ДАТА').get_data(as_text=True)
    assert regs['fresh'].user.email in html


def test_per_page_is_capped_to_known_values(client, admin):
    """?per_page=100000 не має класти сторінку: беремо лише дозволені."""
    from app.admin import _listing

    _login(client, admin)
    with client.application.test_request_context('/admin/users?per_page=100000'):
        assert _listing.per_page_arg(50) == 50
    with client.application.test_request_context('/admin/users?per_page=25'):
        assert _listing.per_page_arg(50) == 25
    assert client.get('/admin/users?per_page=100000').status_code == 200


def test_export_link_carries_active_filters(client, admin):
    _login(client, admin)
    html = client.get('/admin/users?role=admin&q=test').get_data(as_text=True)
    export = re.search(r'href="([^"]*users/export[^"]*)"', html).group(1)
    export = export.replace('&amp;', '&')
    assert 'role=admin' in export and 'q=test' in export
