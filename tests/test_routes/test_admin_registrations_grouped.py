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


def test_grouped_view_shows_course_and_date(client, admin, event_with_two_people):
    course, inst, _ = event_with_two_people
    _login(client, admin)

    html = client.get('/admin/registrations?view=grouped').get_data(as_text=True)

    assert course.title in html
    assert f'data-instance-id="{inst.id}"' in html
    assert f'/admin/registrations/group/{inst.id}/rows' in html
    assert f'/admin/instances/{inst.id}/registrations' in html


def test_grouped_numbers_follow_the_filter(client, admin, event_with_two_people):
    """Заголовок не сміє обіцяти більше, ніж розгорнеться."""
    _, inst, _ = event_with_two_people
    _login(client, admin)

    full = client.get('/admin/registrations?view=grouped').get_data(as_text=True)
    narrowed = client.get(
        '/admin/registrations?view=grouped&status=pending').get_data(as_text=True)

    assert f'data-instance-id="{inst.id}" data-group-total="2"' in full
    assert f'data-instance-id="{inst.id}" data-group-total="1"' in narrowed


def test_empty_group_disappears_under_filter(client, admin, event_with_two_people):
    course, inst, _ = event_with_two_people
    _login(client, admin)

    html = client.get(
        '/admin/registrations?view=grouped&status=cancelled').get_data(as_text=True)

    assert f'data-instance-id="{inst.id}"' not in html


def test_event_link_lives_in_the_header(client, admin, event_with_two_people):
    """Перехід на захід -- іконка в заголовку, а не рядок тексту під ним."""
    _, inst, _ = event_with_two_people
    _login(client, admin)

    html = client.get('/admin/registrations?view=grouped').get_data(as_text=True)

    assert 'admin-disclosure__action' in html
    assert f'/admin/instances/{inst.id}/registrations' in html
    # Іконка без підпису: сам текст на кнопці більше не друкується, але
    # доступна назва лишається -- інакше для скрінрідера це посилання в нікуди.
    assert 'aria-label="Відкрити захід"' in html
    assert '>Відкрити захід<' not in html


def test_grouped_page_does_not_grow_with_events(client, admin):
    """Сторінка -- це числа. 12 заходів мусять коштувати як 2."""
    from sqlalchemy import event as sa_event

    _login(client, admin)

    def _count():
        seen = []

        def _tap(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith('SELECT'):
                seen.append(statement)

        sa_event.listen(db.engine, 'before_cursor_execute', _tap)
        try:
            client.get('/admin/registrations?view=grouped&scope=all')
        finally:
            sa_event.remove(db.engine, 'before_cursor_execute', _tap)
        return len(seen)

    course = _course()
    for _ in range(2):
        _registration(_instance(course))
    db.session.flush()
    few = _count()

    for _ in range(10):
        _registration(_instance(course))
    db.session.flush()
    many = _count()

    assert many - few <= 2, (
        f'12 заходів замість 2 дали +{many - few} SELECT ({few} -> {many}) -- '
        f'схоже, підсумки рахуються поштучно'
    )


def _stat_cards(html):
    """Картки-лічильники сторінки як {підпис: значення}."""
    import re
    return dict((label, value) for value, label in re.findall(
        r'admin-stat-card__value">([^<]*)</span>\s*'
        r'<span class="admin-stat-card__label">([^<]*)<', html))


@pytest.mark.parametrize('view', ['list', 'grouped'])
def test_stat_cards_follow_the_filter(client, admin, event_with_two_people, view):
    """Картки рахують той самий зріз, що й таблиця під ними.

    Раніше вони рахували ВСЮ таблицю реєстрацій: зверху «Всього 5000», а під
    ними -- дюжина рядків за фільтром, і менеджер не мав як це звести.
    """
    _login(client, admin)

    html = client.get(
        f'/admin/registrations?view={view}&scope=all&status=pending'
    ).get_data(as_text=True)

    cards = _stat_cards(html)
    assert cards['Всього'] == '1'
    assert cards['Очікує'] == '1'
    assert cards['Підтверджено'] == '0'


def test_stat_cards_survive_search_and_scope_joins(client, admin, event_with_two_people):
    """Пошук джойнить User, часовий зріз -- CourseInstance: картки мусять
    пережити обидва джойни в одному запиті."""
    _, _, regs = event_with_two_people
    _login(client, admin)

    email = db.session.get(User, regs[0].user_id).email
    response = client.get(
        f'/admin/registrations?scope=upcoming&q={quote(email)}')

    assert response.status_code == 200
    assert _stat_cards(response.get_data(as_text=True))['Всього'] == '1'
